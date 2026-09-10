"""
爬虫运行日志扩展 (v2.0)
──────────────────────
记录每次爬虫运行的统计信息到 spider_run_log 表。

生命周期:
  spider_opened → INSERT (status='running', start_time=NOW())
  定时心跳      → UPDATE (stats 实时更新, 默认每 30s)
  spider_closed → UPDATE (end_time, status, 最终统计 + 关闭快照)

改进要点 (v2.0):
  1. 区分关闭原因: "shutdown" → "interrupted" (不再错误标记为 "failed")
  2. 定时心跳: 每 30s 将当前 stats 写入 DB, 中断时最多丢失 30s 数据
  3. 最终写入重试: write_run_end() 失败时重试 3 次 (指数退避)
  4. 捕获首个错误: 监听 spider_error 信号, 记录首个严重错误
  5. 丰富 extra_info: 关闭时记录活跃桶数、已领取桶数等诊断信息
"""

import json
import logging
import time
import uuid
from typing import Optional

import pymysql
import pymysql.cursors
from scrapy import signals
from scrapy.crawler import Crawler
from scrapy.settings import Settings
from twisted.internet import task

logger = logging.getLogger(__name__)

# ── 关闭原因 → 状态映射 ──────────────────────────────────────────
# Scrapy spider_closed 信号的 reason 参数:
#   "finished"    → 爬虫正常完成
#   "shutdown"    → 用户手动 Ctrl+C / SIGTERM / 引擎关闭
#   "cancelled"   → 爬虫被取消
#   其他自定义值   → 如 "api_failure" (由 spider 自定义)
# ──────────────────────────────────────────────────────────────────
_REASON_STATUS_MAP = {
    "finished":    "completed",
    "shutdown":    "interrupted",   # ← 关键修正: 不再错误标记为 "failed"
    "cancelled":   "interrupted",
    "api_failure": "failed",
}

_REASON_MESSAGE_MAP = {
    "finished":    None,
    "shutdown":    "用户手动中断 (Ctrl+C/SIGTERM)",
    "cancelled":   "爬虫被取消",
    "api_failure": "API 业务错误终止",
}


class SpiderRunLogExtension:
    """记录每次爬虫运行的统计信息到 spider_run_log 表的 Scrapy Extension

    生命周期:
      spider_opened → INSERT (status='running', start_time=NOW())
      定时心跳      → UPDATE (stats 实时更新, 默认每 30s)
      spider_closed → UPDATE (end_time, status, 最终统计 + 关闭快照)
    """

    def __init__(self, crawler: Crawler):
        self.crawler = crawler
        self.settings: Settings = crawler.settings
        self.run_id: Optional[str] = None
        self._spider: Optional[object] = None
        self._heartbeat_call: Optional[task.LoopingCall] = None
        self._first_error: Optional[str] = None
        self._start_extra: Optional[dict] = None  # 保存启动时的 extra_info, 供关闭时合并
        self._finalized: bool = False             # 是否已写最终记录 (防止重复落库)

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        ext = cls(crawler=crawler)

        # 绑定生命周期信号
        crawler.signals.connect(
            ext.spider_opened, signal=signals.spider_opened
        )
        crawler.signals.connect(
            ext.spider_closed, signal=signals.spider_closed
        )
        # 捕获运行期间首个严重错误
        crawler.signals.connect(
            ext._on_spider_error, signal=signals.spider_error
        )
        # 兜底: 注册 reactor 关闭钩子, 覆盖"强制关闭 (二次 Ctrl+C)"
        # 导致 spider_closed 未触发的场景 (见 _on_reactor_shutdown)
        ext._register_reactor_shutdown_hook()
        return ext

    def _register_reactor_shutdown_hook(self):
        """注册 Twisted reactor 关闭钩子 (进程退出前最后一道兜底)

        背景: 用户按两次 Ctrl+C 时, Scrapy 走 `_signal_kill` → `reactor.stop()`
        强制不干净关闭, `spider_closed` 信号可能来不及发出 → 最终记录不落库,
        spider_run_log.status 永久停留 'running'。

        reactor 的 "before"/"shutdown" 触发器在 reactor 停止前**必定同步执行**
        (优雅关闭与强制关闭都会走到), 在此同步落库可兜底该场景。
        """
        try:
            from twisted.internet import reactor
            # 注: Twisted 类型存根将 eventType 误标为 callable, 此报警为类型噪音,
            # 运行时正常 (Scrapy 自身 crawler.py 亦如此调用)。
            reactor.addSystemEventTrigger(
                "before", "shutdown", self._on_reactor_shutdown
            )
        except Exception as e:
            logger.warning("注册 reactor 关闭兜底钩子失败: %s", e)

    def _on_reactor_shutdown(self):
        """reactor 关闭前同步落库 (兜底强制关闭场景)

        若 spider_closed 已正常写入 (_finalized=True) 则直接跳过。
        DB 写入使用同步 pymysql, 在 reactor shutdown 触发器中可安全执行。
        """
        if self._finalized or not self.run_id:
            return
        try:
            stats = self.crawler.stats
            req = stats.get_value("downloader/request_count") if stats else 0
            items = stats.get_value("item_scraped_count") if stats else 0
            errors = stats.get_value("log_count/ERROR") if stats else 0
            last_page = getattr(self._spider, "last_page", 0) if self._spider else 0
            self.write_run_end(
                status="interrupted",
                total_requests=req or 0,
                total_items=items or 0,
                total_errors=errors or 0,
                last_page=last_page or 0,
                error_message="进程强制退出 (未走正常关闭流程, 由 reactor 钩子兜底)",
                shutdown_extra={"shutdown_reason": "reactor_shutdown_fallback"},
            )
            logger.info("reactor 关闭兜底: 已将运行记录落库 (status=interrupted)")
        except Exception as e:
            logger.warning("reactor 关闭兜底写入失败: %s", e)

    # ═══════════════════════════════════════════════════════════════
    # 数据库连接
    # ═══════════════════════════════════════════════════════════════

    def _connect(self):
        return pymysql.connect(
            host=self.settings.get("MYSQL_HOST"),
            port=self.settings.getint("MYSQL_PORT"),
            user=self.settings.get("MYSQL_USER"),
            password=self.settings.get("MYSQL_PASSWORD"),
            database=self.settings.get("MYSQL_DATABASE"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    # ═══════════════════════════════════════════════════════════════
    # 信号处理
    # ═══════════════════════════════════════════════════════════════

    def spider_opened(self, spider=None):
        """Scrapy 信号: 爬虫启动"""
        self._spider = spider

        extra = {
            "start_page": getattr(spider, "start_page", None),
            "page_size": getattr(spider, "page_size", None),
            "max_pages": getattr(spider, "max_pages", None),
        }
        spider_name = spider.name if spider else "unknown_spider"
        self.write_run_start(spider_name, extra)

        # 启动定时心跳 (每 30s 将当前 stats 写入 DB)
        self._start_heartbeat()

    def spider_closed(self, spider=None, reason="finished"):
        """Scrapy 信号: 爬虫关闭

        改进点:
          1. 先停心跳, 再写最后一次心跳数据 (确保最新 stats 落库)
          2. 区分关闭原因: shutdown → interrupted, finished → completed
          3. 捕获活跃桶数等诊断信息写入 extra_info
          4. 最终写入失败时重试 3 次
        """
        # 1. 停止心跳
        self._stop_heartbeat()

        # 2. 最后一次心跳写入 (确保最新数据落库)
        self._heartbeat()

        # 3. 读取当前统计
        stats = self.crawler.stats
        req_count = stats.get_value("downloader/request_count") if stats else 0
        item_count = stats.get_value("item_scraped_count") if stats else 0
        err_count = stats.get_value("log_count/ERROR") if stats else 0
        last_page = getattr(spider, "last_page", 0) if spider else 0

        # 4. 区分关闭原因
        status = _REASON_STATUS_MAP.get(reason, "failed")
        error_message = _REASON_MESSAGE_MAP.get(
            reason, f"关闭原因: {reason}"
        )

        # 5. 构建关闭时的额外诊断信息
        shutdown_extra = self._build_shutdown_extra(spider, reason)

        # 6. 带重试的最终写入
        self._write_run_end_with_retry(
            status=status,
            total_requests=req_count or 0,
            total_items=item_count or 0,
            total_errors=err_count or 0,
            last_page=last_page,
            error_message=error_message,
            shutdown_extra=shutdown_extra,
        )

    def _on_spider_error(self, failure, response=None, spider=None):
        """Scrapy 信号: 爬虫处理过程中发生错误

        仅捕获首个错误信息, 用于最终写入 error_message 的补充诊断。
        """
        if self._first_error is None:
            # 截断过长的错误信息
            msg = str(failure.value) if failure else "未知错误"
            self._first_error = msg[:500]
            logger.debug("捕获首个爬虫错误: %s", self._first_error)

    # ═══════════════════════════════════════════════════════════════
    # 定时心跳 (核心改进)
    # ═══════════════════════════════════════════════════════════════

    def _start_heartbeat(self):
        """启动定时心跳: 每 N 秒将当前 stats 写入 DB"""
        interval = self.settings.getint("SPIDER_LOG_HEARTBEAT_INTERVAL", 30)
        if interval <= 0:
            return  # 允许通过设置为 0 来禁用心跳
        self._heartbeat_call = task.LoopingCall(self._heartbeat)
        self._heartbeat_call.start(interval, now=False)
        logger.info("心跳已启动: 每 %ds 更新 spider_run_log 统计", interval)

    def _stop_heartbeat(self):
        """停止定时心跳"""
        if self._heartbeat_call and self._heartbeat_call.running:
            self._heartbeat_call.stop()
            self._heartbeat_call = None
            logger.debug("心跳已停止")

    def _heartbeat(self):
        """单次心跳: 将当前 stats 写入 DB (仅更新统计字段, 不动 end_time/status)"""
        if not self.run_id:
            return

        try:
            stats = self.crawler.stats
            req = stats.get_value("downloader/request_count") if stats else 0
            items = stats.get_value("item_scraped_count") if stats else 0
            errors = stats.get_value("log_count/ERROR") if stats else 0
            last_page = (
                getattr(self._spider, "last_page", 0) if self._spider else 0
            )

            self._update_stats(
                total_requests=req or 0,
                total_items=items or 0,
                total_errors=errors or 0,
                last_page=last_page or 0,
            )
        except Exception as e:
            logger.warning("心跳写入失败: %s", e)

    def _update_stats(self, total_requests=0, total_items=0,
                      total_errors=0, last_page=0):
        """仅更新统计字段 (不改变 end_time/status/error_message/extra_info)

        与 write_run_end() 的区别:
          - 不设置 end_time (爬虫仍在运行)
          - 不改变 status (保持 'running')
          - 不修改 error_message / extra_info
        """
        if not self.run_id:
            return

        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE spider_run_log SET
                               total_requests = %s,
                               total_items = %s,
                               total_errors = %s,
                               last_page = %s
                           WHERE run_id = %s""",
                        (total_requests, total_items, total_errors,
                         last_page, self.run_id),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("更新统计字段失败: %s", e)

    # ═══════════════════════════════════════════════════════════════
    # 通用方法
    # ═══════════════════════════════════════════════════════════════

    def write_run_start(self, spider_name: str, extra: Optional[dict] = None):
        """写入运行开始记录 (status='running')"""
        self._mark_interrupted(spider_name)

        self.run_id = str(uuid.uuid4())
        self._start_extra = extra or {}
        extra_info = json.dumps(self._start_extra, ensure_ascii=False)
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO spider_run_log
                           (run_id, spider_name, start_time, status, extra_info)
                           VALUES (%s, %s, NOW(), 'running', %s)""",
                        (self.run_id, spider_name, extra_info),
                    )
                conn.commit()
                logger.info(
                    "Running log has been recorded: run_id=%s, spider=%s",
                    self.run_id, spider_name,
                )
            finally:
                conn.close()
        except Exception as e:
            logger.warning("写入 spider_run_log (启动) 失败: %s", e)

    def _mark_interrupted(self, spider_name: str):
        """将同名爬虫上次异常终止的遗留 running 记录标记为 interrupted

        触发场景:
          - 进程被 kill -9 强杀 (spider_closed 信号未触发)
          - 断电/系统崩溃
          - write_run_end() 最终写入失败 (DB 连接异常等)

        注意: 心跳已保障 stats 接近最新 (最多丢失 30s 数据),
        此处只需标记状态和 end_time。
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE spider_run_log SET
                               end_time = NOW(),
                               status = 'interrupted',
                               error_message = CONCAT(
                                   COALESCE(error_message, ''),
                                   ' | 异常终止 (上次运行未正常关闭, 由下次启动检测)'
                               )
                           WHERE status = 'running' AND spider_name = %s""",
                        (spider_name,)
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("标记中断记录失败: %s", e)

    def _build_shutdown_extra(self, spider, reason: str) -> dict:
        """构建关闭时的额外诊断信息, 合并到 extra_info 中"""
        extra = {}

        # 从 spider 读取运行状态
        if spider:
            active = getattr(spider, "_active_buckets", None)
            extra["active_buckets_at_shutdown"] = (
                len(active) if isinstance(active, dict) else 0
            )
            extra["claimed_buckets"] = getattr(spider, "_claimed_buckets", 0)
            extra["last_page"] = getattr(spider, "last_page", 0)

        # 关闭原因
        extra["shutdown_reason"] = reason

        # 首个错误 (若有)
        if self._first_error:
            extra["first_error"] = self._first_error

        return extra

    def _write_run_end_with_retry(
        self,
        status: str,
        total_requests: int = 0,
        total_items: int = 0,
        total_errors: int = 0,
        last_page: int = 0,
        error_message: Optional[str] = None,
        shutdown_extra: Optional[dict] = None,
        max_retries: int = 3,
    ):
        """带重试的最终写入

        在 shutdown 期间 DB 连接可能不稳定 (连接池正在关闭等),
        重试 3 次 + 指数退避, 尽力保障最终记录落库。
        """
        for attempt in range(max_retries):
            try:
                self.write_run_end(
                    status=status,
                    total_requests=total_requests,
                    total_items=total_items,
                    total_errors=total_errors,
                    last_page=last_page,
                    error_message=error_message,
                    shutdown_extra=shutdown_extra,
                )
                return  # 成功, 退出
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                    logger.warning(
                        "最终写入失败 (第 %d/%d 次), %0.1fs 后重试: %s",
                        attempt + 1, max_retries, wait, e,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "最终写入失败 (已重试 %d 次), 数据可能丢失: %s",
                        max_retries, e,
                    )

    def write_run_end(
        self,
        status: str,
        total_requests: int = 0,
        total_items: int = 0,
        total_errors: int = 0,
        last_page: int = 0,
        error_message: Optional[str] = None,
        shutdown_extra: Optional[dict] = None,
    ):
        """更新运行结束记录 (status + 统计信息 + 关闭快照)

        改进点:
          - 合并启动时的 extra_info 与关闭时的 shutdown_extra
          - 一并更新 extra_info 字段, 保留完整运行上下文
        """
        if not self.run_id:
            return

        # 合并启动 + 关闭信息
        merged_extra = dict(self._start_extra or {})
        if shutdown_extra:
            merged_extra["_shutdown"] = shutdown_extra
        extra_info = json.dumps(merged_extra, ensure_ascii=False)

        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE spider_run_log SET
                               end_time = NOW(),
                               status = %s,
                               total_requests = %s,
                               total_items = %s,
                               total_errors = %s,
                               last_page = %s,
                               error_message = %s,
                               extra_info = %s
                           WHERE run_id = %s""",
                        (
                            status,
                            total_requests,
                            total_items,
                            total_errors,
                            last_page,
                            error_message,
                            extra_info,
                            self.run_id,
                        ),
                    )
                conn.commit()
                self._finalized = True  # 标记已写最终记录 (reactor 兜底钩子据此跳过)
                logger.info(
                    "运行日志已更新: run_id=%s, status=%s, "
                    "requests=%d, items=%d, errors=%d, last_page=%d",
                    self.run_id, status, total_requests,
                    total_items, total_errors, last_page,
                )
            finally:
                conn.close()
        except Exception as e:
            logger.warning("写入 spider_run_log (关闭) 失败: %s", e)
            raise  # 重新抛出, 让 _write_run_end_with_retry 处理重试