"""
v2 爬虫 Windows 兼容运行器
──────────────────────────
按关键词搜索文献，需提供 scholarin.cn 登录 Cookie。

Linux/Mac 用户可直接用:
  scrapy crawl pubscholar_v2 -a query="人工智能"
"""

import json
import logging
import os
import random
import sys
import time
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
from academic_spiders.utils.resume import V2_SPIDER_NAMES, resolve_start_page
from academic_spiders.utils.signing import build_signature_headers

logger = logging.getLogger("v2_runner")


class V2SpiderRunner:
    """v2 API 同步爬虫运行器 — 按关键词搜索"""

    API_URL = "https://scholarin.cn/hky/api/v2/resources/article"
    SECRET = "6m6pingbinwaktg227gngifoocrfbo95"
    FINGER = "c84069ed4e4270f9897e3a07acb81355"

    def __init__(
        self,
        query: str,
        cookie: str = "",
        xsrf_token: str = "",
        user_id: str = "",
        page_size: int = 20,
        max_pages: Optional[int] = None,
        start_page: int = 1,
        end_page: Optional[int] = None,
        min_delay: float = 1.5,
        max_delay: float = 3.0,
    ):
        self.query = query
        self.user_id = user_id or "c9ca380e54f3455ca27bdeb6f921f7b0"
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
        from scrapy.settings import Settings
        s = Settings()
        for k, v in settings.items():
            s.set(k, v)
        self.mysql_pipeline = MySQLPipeline(settings=s)
        self.run_log = SpiderRunLogPipeline(settings=s)

    def _build_headers(self) -> dict:
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
            "Origin": "https://scholarin.cn",
            "Referer": "https://scholarin.cn/explore",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            **sig,
        }
        if self.xsrf_token:
            headers["X-XSRF-TOKEN"] = self.xsrf_token
        return headers

    def _fetch_page(self, page: int) -> Optional[dict]:
        payload = {
            "uid": self.user_id,
            "user_id": self.user_id,
            "article_query": {
                "query": self.query,
                "page": page,
                "order_field": "pub_date",
                "order_direction": "desc",
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
                page, response.status_code, response.text[:300],
            )
            return None

        data = response.json()
        if data.get("failure") is True:
            logger.error(
                "第 %d 页 API 错误: %s",
                page, data.get("cause", data.get("message", "未知")),
            )
            return None

        return data

    def _record_to_item(self, record: dict, page: int) -> ArticleItem:
        """v2 记录 → ArticleItem"""
        return record_to_item(record, page, api_version="v2")

    def _fetch_total(self) -> int:
        """获取搜索总条数"""
        data = self._fetch_page(1)
        if data:
            return data.get("totalElements", 0)
        return 0

    def run(self):
        logger.info(
            "v2 爬虫启动: query='%s', start_page=%d, page_size=%d, max_pages=%s",
            self.query, self.start_page, self.page_size,
            self.max_pages or "无限制",
        )

        if not self.query:
            logger.error("必须提供搜索关键词 (--query)")
            return

        # 写入运行日志 (spider_run_log 表)
        if self.run_log:
            self.run_log.write_run_start(
                "v2_runner",
                extra={
                    "query": self.query,
                    "start_page": self.start_page,
                    "page_size": self.page_size,
                    "max_pages": self.max_pages,
                },
            )

        try:
            page = self.start_page
            consecutive_errors = 0

            while True:
                time.sleep(random.uniform(self.min_delay, self.max_delay))

                data = self._fetch_page(page)
                if data is None:
                    consecutive_errors += 1
                    if consecutive_errors > 5:
                        logger.error("连续错误过多，停止")
                        break
                    page += 1
                    continue

                content = data.get("content") or []
                total = data.get("totalElements", 0)
                total_pages = data.get("totalPages", 0)
                self.last_page = page  # 供运行日志记录最后爬取页码

                # 异常响应检测: totalPages=0 通常是 API 限流, 非真正最后一页
                if total_pages <= 0:
                    consecutive_errors += 1
                    logger.warning(
                        "第 %d 页响应异常 (totalPages=0, content=%d 条)，"
                        "连续异常 %d 次",
                        page, len(content), consecutive_errors,
                    )
                    if consecutive_errors > 5:
                        logger.error("连续异常过多，停止")
                        break
                    page += 1
                    continue

                consecutive_errors = 0
                self.stats["pages"] += 1

                if page == self.start_page:
                    logger.info(
                        "首请求成功: total=%s, total_pages=%s, page_size=%d",
                        f"{total:,}", f"{total_pages:,}", len(content),
                    )

                for record in content:
                    item = self._record_to_item(record, page)
                    self.json_pipeline.process_item(item, None)
                    if self.mysql_pipeline:
                        self.mysql_pipeline.process_item(item, None)
                    self.stats["items"] += 1

                logger.info(
                    "第 %d/%d 页完成: %d 条, 累计 %s 条",
                    page, total_pages, len(content),
                    f"{self.stats['items']:,}",
                )

                if page >= total_pages:
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
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="公益学术平台v2 API 爬虫 — 按关键词搜索 (需登录 Cookie)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_v2_spider.py -q "人工智能" --cookie "XSRF-TOKEN=...; ..." --xsrf-token "..." --uid "..."

获取 Cookie 的方法:
  1. 浏览器登录 https://scholarin.cn
  2. F12 → Network → 搜索一次
  3. 找到 /hky/api/v2/resources/article 请求
  4. 复制 Request Headers 中的 Cookie 值
  5. 复制 X-XSRF-TOKEN 的值
  6. 复制 Payload 中的 uid 值
        """,
    )
    parser.add_argument("-q", "--query", required=True, help="搜索关键词")
    parser.add_argument("-p", "--pages", type=int, default=1)
    parser.add_argument("--all", action="store_true", help="获取全部结果")
    parser.add_argument("-s", "--page-size", type=int, default=20)
    parser.add_argument("--start-page", type=int, default=None,
                        help="起始页码 (默认: 自动从上次运行断点续爬)")
    parser.add_argument("--end-page", type=int, default=None,
                        help="结束页码 (爬到此页后停止, 默认无限制)")
    parser.add_argument("--cookie", type=str, default="",
                        help="Cookie 字符串 (必填！)")
    parser.add_argument("--xsrf-token", type=str, default="",
                        help="X-XSRF-TOKEN 值 (必填！)")
    parser.add_argument("--uid", type=str, default="",
                        help="登录用户 UID (必填！)")
    parser.add_argument("--min-delay", type=float, default=1.5)
    parser.add_argument("--max-delay", type=float, default=3.0)
    parser.add_argument("--no-mysql", action="store_true")
    parser.add_argument("--db-host", type=str, default="localhost")
    parser.add_argument("--db-port", type=int, default=3306)
    parser.add_argument("--db-user", type=str, default="root")
    parser.add_argument("--db-password", type=str, default="200310")
    parser.add_argument("--db-name", type=str,
                        default=os.getenv("MYSQL_DATABASE", "academicdb"),
                        help="数据库名 (默认: MYSQL_DATABASE 环境变量或 academicdb)")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    # 日志: 控制台 + 文件 (logs/runner_v2.log, 50MB 轮转 × 10)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    setup_file_logging("runner_v2.log",
                        level=logging.DEBUG if args.verbose else logging.INFO,
                        db_name=args.db_name)

    if not args.cookie and not args.all:
        logger.warning(
            "未提供 --cookie。v2 API 需要登录 Cookie。"
            "使用 python run_v2_spider.py --help 查看获取方法。"
        )

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
        start_page = resolve_start_page(db_config, V2_SPIDER_NAMES)
    else:
        start_page = 1

    runner = V2SpiderRunner(
        query=args.query,
        cookie=args.cookie,
        xsrf_token=args.xsrf_token,
        user_id=args.uid,
        page_size=min(args.page_size, 50),
        max_pages=None if args.all else args.pages,
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
