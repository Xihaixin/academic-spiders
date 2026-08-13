"""
v1 爬虫 Windows 兼容运行器
──────────────────────────
使用 requests 同步请求 + Scrapy Pipeline 存储。
复用 academic_spiders 的 Items, Pipelines, 签名工具。

Linux/Mac 用户可直接用: scrapy crawl pubscholar_v1
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests

from academic_spiders.items import ArticleItem
from academic_spiders.pipelines import (
    MySQLPipeline,
    JsonExportPipeline,
    SpiderRunLogPipeline,
)
from academic_spiders.utils.logging_config import setup_file_logging
from academic_spiders.utils.parsers import record_to_item
from academic_spiders.utils.resume import V1_SPIDER_NAMES, resolve_start_page
from academic_spiders.utils.signing import build_signature_headers

logger = logging.getLogger("v1_runner")


class V1SpiderRunner:
    """v1 API 同步爬虫运行器"""

    API_URL = "https://pubscholar.cn/hky/open/resources/api/v1/articles"
    SECRET = "6m6pingbinwaktg227gngifoocrfbo95"
    FINGER = "c84069ed4e4270f9897e3a07acb81355"
    USER_ID = "0b68c4370e9a43e4ad1690fdd31f643f"

    def __init__(
        self,
        cookie: str = "",
        xsrf_token: str = "",
        page_size: int = 50,
        max_pages: Optional[int] = None,
        start_page: int = 1,
        end_page: Optional[int] = None,
        min_delay: float = 1.5,
        max_delay: float = 3.0,
    ):
        self.page_size = page_size
        self.max_pages = max_pages
        self.start_page = start_page
        self.end_page = end_page
        self.min_delay = min_delay
        self.max_delay = max_delay

        # 会话
        self.session = requests.Session()
        if cookie:
            for item in cookie.split(";"):
                item = item.strip()
                if "=" in item:
                    name, _, value = item.partition("=")
                    self.session.cookies.set(name.strip(), value.strip())

        self.xsrf_token = xsrf_token

        # Pipelines
        self.json_pipeline = JsonExportPipeline(output_dir="output")
        self.mysql_pipeline: Optional[MySQLPipeline] = None
        self.run_log: Optional[SpiderRunLogPipeline] = None

        # 统计
        self.stats = {"pages": 0, "items": 0, "errors": 0}
        self.last_page = 0

    def init_mysql(self, settings: dict):
        """初始化 MySQL pipeline + 运行日志 pipeline"""
        from scrapy.settings import Settings
        s = Settings()
        for k, v in settings.items():
            s.set(k, v)
        self.mysql_pipeline = MySQLPipeline(settings=s)
        self.run_log = SpiderRunLogPipeline(settings=s)

    def _build_headers(self) -> dict:
        """构建请求头"""
        sig = build_signature_headers(self.SECRET, self.FINGER)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"
            ),
            "Origin": "https://pubscholar.cn",
            "Referer": "https://pubscholar.cn/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            **sig,
        }
        if self.xsrf_token:
            headers["X-XSRF-TOKEN"] = self.xsrf_token
        return headers

    def _fetch_page(self, page: int) -> Optional[dict]:
        """获取单页数据"""
        payload = {
            "page": page,
            "size": self.page_size,
            "order_field": "date",
            "order_direction": "desc",
            "user_id": self.USER_ID,
            "lang": "zh",
            "aggregations": {
                "type": "", "subject": "", "year": "", "keyword": "",
                "collection": "", "lang": "C", "source": "",
                "correspAuthor": "", "funding": "", "institution": "",
                "license": "",
            },
        }

        response = self.session.post(
            self.API_URL,
            json=payload,
            headers=self._build_headers(),
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                "第 %d 页 HTTP %d: %s",
                page, response.status_code, response.text[:200],
            )
            return None

        data = response.json()
        if data.get("failure") is True:
            logger.error(
                "第 %d 页 API 错误: %s", page, data.get("cause", "未知"),
            )
            return None

        return data

    def _record_to_item(self, record: dict, page: int) -> ArticleItem:
        """将 API 记录转为 ArticleItem"""
        return record_to_item(record, page, api_version="v1")

    def run(self):
        """主运行循环"""
        logger.info(
            "v1 爬虫启动: start_page=%d, page_size=%d, max_pages=%s",
            self.start_page, self.page_size,
            self.max_pages or "无限制",
        )

        # 写入运行日志 (spider_run_log 表)
        if self.run_log:
            self.run_log.write_run_start(
                "v1_runner",
                extra={
                    "start_page": self.start_page,
                    "page_size": self.page_size,
                    "max_pages": self.max_pages,
                },
            )

        try:
            page = self.start_page
            while True:
                # 请求间隔
                delay = __import__("random").uniform(
                    self.min_delay, self.max_delay
                )
                time.sleep(delay)

                # 获取页面
                data = self._fetch_page(page)
                if data is None:
                    self.stats["errors"] += 1
                    if self.stats["errors"] > 10:
                        logger.error("连续错误过多，停止")
                        break
                    page += 1
                    continue

                # 提取记录
                content = data.get("content") or []
                total = data.get("total", 0)
                is_last = data.get("is_last", False)  # 默认 False, 避免误判
                total_pages = data.get("total_pages", 0)
                self.last_page = page  # 供运行日志记录最后爬取页码

                # 异常响应检测: total_pages=0 通常是 API 限流, 非真正最后一页
                if total_pages <= 0:
                    self.stats["errors"] += 1
                    logger.warning(
                        "第 %d 页响应异常 (total_pages=0, content=%d 条)，"
                        "连续异常 %d 次",
                        page, len(content), self.stats["errors"],
                    )
                    if self.stats["errors"] > 5:
                        logger.error("连续异常过多，停止 (疑似 API 限流/Cookie 过期)")
                        break
                    page += 1
                    continue

                self.stats["errors"] = 0  # 重置错误计数
                self.stats["pages"] += 1

                if page == self.start_page:
                    logger.info(
                        "首请求成功: total=%s, total_pages=%s, page_size=%d",
                        f"{total:,}", f"{total_pages:,}", len(content),
                    )

                # 逐条处理
                for record in content:
                    item = self._record_to_item(record, page)
                    # JSON 导出
                    self.json_pipeline.process_item(item, None)
                    # MySQL 存储
                    if self.mysql_pipeline:
                        self.mysql_pipeline.process_item(item, None)
                    self.stats["items"] += 1

                logger.info(
                    "第 %d/%d 页完成: %d 条, 累计约 %s 条",
                    page, total_pages, len(content),
                    f"{page * self.page_size:,}",
                )

                # 翻页判断
                if is_last:
                    logger.info("已到最后一页 (第 %d 页)", page)
                    break

                if self.end_page and page >= self.end_page:
                    logger.info("已达指定结束页: %d", self.end_page)
                    break

                if self.max_pages and page >= (self.start_page + self.max_pages - 1):
                    logger.info("已达最大页数限制: %d", self.max_pages)
                    break

                page += 1

        except KeyboardInterrupt:
            logger.info("用户中断")
        finally:
            self._shutdown()

    def _shutdown(self):
        """清理资源"""
        logger.info(
            "爬取结束: pages=%d, items=%d, errors=%d",
            self.stats["pages"], self.stats["items"], self.stats["errors"],
        )
        # 更新运行日志 (spider_run_log 表)
        if self.run_log:
            has_errors = self.stats["errors"] > 0
            self.run_log.write_run_end(
                status="failed" if has_errors else "completed",
                total_requests=self.stats["pages"],
                total_items=self.stats["items"],
                total_errors=self.stats["errors"],
                last_page=self.last_page,
            )
        self.json_pipeline.close_spider(None)
        if self.mysql_pipeline:
            self.mysql_pipeline.close_spider(None)
        self.session.close()


# ═══════════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="慧科研 v1 API 爬虫 (Windows 兼容运行器)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试: 爬 3 页，每页 10 条，不写 MySQL
  python run_v1_spider.py -p 3 -s 10 --no-mysql

  # 生产: 爬全部，每页 50 条
  python run_v1_spider.py --all

  # 断点续爬
  python run_v1_spider.py --all --start-page 1000
        """,
    )
    parser.add_argument("-p", "--pages", type=int, default=1,
                        help="爬取页数 (默认 1)")
    parser.add_argument("--all", action="store_true",
                        help="爬取全部页 (需配合 max-pages 或全部)")
    parser.add_argument("-s", "--page-size", type=int, default=50,
                        help="每页条数 (默认 50, 最大 50)")
    parser.add_argument("--start-page", type=int, default=None,
                        help="起始页码 (默认: 自动从上次运行断点续爬)")
    parser.add_argument("--end-page", type=int, default=None,
                        help="结束页码 (爬到此页后停止, 默认无限制)")
    parser.add_argument("--cookie", type=str,
                        default="XSRF-TOKEN=115318a2-c245-446e-b005-1cee19f9fe49; JSESSIONID=ADE2864C54C437C14B2E7CB2C2CAB732",
                        help="Cookie 字符串")
    parser.add_argument("--xsrf-token", type=str,
                        default="115318a2-c245-446e-b005-1cee19f9fe49",
                        help="XSRF-TOKEN 值")
    parser.add_argument("--min-delay", type=float, default=1.5,
                        help="最小请求间隔秒数")
    parser.add_argument("--max-delay", type=float, default=3.0,
                        help="最大请求间隔秒数")
    parser.add_argument("--no-mysql", action="store_true",
                        help="禁用 MySQL 存储")
    parser.add_argument("--db-host", type=str, default="localhost")
    parser.add_argument("--db-port", type=int, default=3306)
    parser.add_argument("--db-user", type=str, default="root")
    parser.add_argument("--db-password", type=str, default="200310")
    parser.add_argument("--db-name", type=str,
                        default=os.getenv("MYSQL_DATABASE", "academicdb"),
                        help="数据库名 (默认: MYSQL_DATABASE 环境变量或 academicdb)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="详细日志")

    args = parser.parse_args()

    # 日志: 控制台 + 文件 (logs/runner_v1.log, 50MB 轮转 × 10)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    setup_file_logging("runner_v1.log",
                        level=logging.DEBUG if args.verbose else logging.INFO,
                        db_name=args.db_name)

    max_pages = None
    if not args.all:
        max_pages = args.pages

    db_config = {
        "MYSQL_HOST": args.db_host,
        "MYSQL_PORT": args.db_port,
        "MYSQL_USER": args.db_user,
        "MYSQL_PASSWORD": args.db_password,
        "MYSQL_DATABASE": args.db_name,
        "MYSQL_POOL_SIZE": 4,
    }

    # 起始页: 显式指定 > 自动断点续爬 > 默认 1
    if args.start_page is not None:
        start_page = max(args.start_page, 1)
    elif not args.no_mysql:
        start_page = resolve_start_page(db_config, V1_SPIDER_NAMES)
    else:
        start_page = 1

    runner = V1SpiderRunner(
        cookie=args.cookie,
        xsrf_token=args.xsrf_token,
        page_size=min(args.page_size, 50),
        max_pages=max_pages,
        start_page=start_page,
        end_page=args.end_page,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
    )

    if not args.no_mysql:
        runner.init_mysql(db_config)

    runner.run()


if __name__ == "__main__":
    main()
