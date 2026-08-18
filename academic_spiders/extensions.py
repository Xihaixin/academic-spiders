import json
import logging
import uuid
from typing import Optional

import pymysql
import pymysql.cursors
from scrapy import signals
from scrapy.crawler import Crawler
from scrapy.settings import Settings

logger = logging.getLogger(__name__)


class SpiderRunLogExtension:
    """记录每次爬虫运行的统计信息到 spider_run_log 表的 Scrapy Extension

    生命周期:
      spider_opened → INSERT (status='running', start_time=NOW())
      spider_closed → UPDATE (end_time, status, 统计信息)
    """

    def __init__(self, crawler: Crawler):
        self.crawler = crawler
        self.settings: Settings = crawler.settings
        self.run_id: Optional[str] = None

    @classmethod
    def from_crawler(cls, crawler: Crawler):
        # 1. 实例化 Extension
        ext = cls(crawler=crawler)

        # 2. 绑定生命周期信号
        crawler.signals.connect(
            ext.spider_opened, signal=signals.spider_opened
        )
        crawler.signals.connect(
            ext.spider_closed, signal=signals.spider_closed
        )
        return ext

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

    def spider_opened(self, spider=None):
        """Scrapy 信号: 爬虫启动"""
        extra = {
            "start_page": getattr(spider, "start_page", None),
            "page_size": getattr(spider, "page_size", None),
            "max_pages": getattr(spider, "max_pages", None),
        }
        spider_name = spider.name if spider else "unknown_spider"
        self.write_run_start(spider_name, extra)

    def spider_closed(self, spider=None, reason="finished"):
        """Scrapy 信号: 爬虫关闭"""
        stats = self.crawler.stats
        status = "completed" if reason == "finished" else "failed"

        req_count = stats.get_value("downloader/request_count") if stats else 0
        item_count = stats.get_value("item_scraped_count") if stats else 0
        err_count = stats.get_value("log_count/ERROR") if stats else 0

        self.write_run_end(
            status=status,
            total_requests=req_count or 0,
            total_items=item_count or 0,
            total_errors=err_count or 0,
            last_page=getattr(spider, "last_page", 0) if spider else 0,
            error_message=None if status == "completed" else f"关闭原因: {reason}",
        )

    # ── 通用方法 ──────

    def write_run_start(self, spider_name: str, extra: Optional[dict] = None):
        """写入运行开始记录 (status='running')"""
        self._mark_interrupted(spider_name)

        self.run_id = str(uuid.uuid4())
        extra_info = json.dumps(extra or {}, ensure_ascii=False)
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
        """将同名爬虫上次异常终止的遗留 running 记录标记为 interrupted"""
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE spider_run_log SET
                               end_time = NOW(),
                               status = 'interrupted',
                               error_message = '异常终止 (上次运行未正常关闭)'
                           WHERE status = 'running' AND spider_name = %s""",
                        (spider_name,)
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("标记中断记录失败: %s", e)

    def write_run_end(
        self,
        status: str,
        total_requests: int = 0,
        total_items: int = 0,
        total_errors: int = 0,
        last_page: int = 0,
        error_message: Optional[str] = None,
    ):
        """更新运行结束记录 (status + 统计信息)"""
        if not self.run_id:
            return

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
                               error_message = %s
                           WHERE run_id = %s""",
                        (
                            status,
                            total_requests,
                            total_items,
                            total_errors,
                            last_page,
                            error_message,
                            self.run_id,
                        ),
                    )
                conn.commit()
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