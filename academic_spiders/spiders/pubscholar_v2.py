"""
公益学术平台v2 接口爬虫
─────────────────
接口: POST https://scholarin.cn/hky/api/v2/resources/article
认证: 需要登录 Cookie (pub_ticket / JSESSIONID)
功能: 按关键词搜索文献，支持自动翻页
"""

import hashlib
import json
import logging
from typing import Any, Generator

import scrapy
from scrapy import Request, signals
from scrapy.http import Response

from academic_spiders.items import ArticleItem
from academic_spiders.utils.parsers import record_to_item
from academic_spiders.utils.resume import V2_SPIDER_NAMES, resolve_start_page

logger = logging.getLogger(__name__)


class PubscholarV2Spider(scrapy.Spider):
    """
    v2 登录接口爬虫 — 按关键词搜索

    启动示例:
      scrapy crawl pubscholar_v2 -a query="人工智能"

      限制页数:
      scrapy crawl pubscholar_v2 -a query="人工智能" -s V2_MAX_PAGES=10
    """

    name = "pubscholar_v2"

    # 运行状态 (供 SpiderRunLogExtension 读取)
    last_page = 0
    _abnormal_count = 0

    # 默认配置
    api_url = "https://scholarin.cn/hky/api/v2/resources/article"
    user_id = "c9ca380e54f3455ca27bdeb6f921f7b0"
    page_size = 20
    max_pages = None
    start_page = 1
    end_page = None
    query = ""
    order_field = "pub_date"
    order_direction = "desc"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        s = crawler.settings
        spider.api_url = s.get("V2_API_URL", spider.api_url)
        spider.user_id = s.get("V2_USER_ID", spider.user_id)
        spider.page_size = s.getint("V2_PAGE_SIZE")
        spider.max_pages = s.getint("V2_MAX_PAGES") or None
        spider.end_page = s.getint("V2_END_PAGE") or None
        # 起始页: 显式指定 > 自动断点续爬 > 默认 1
        raw_start = s.get("V2_START_PAGE")
        if raw_start:
            spider.start_page = max(int(raw_start), 1)
        else:
            spider.start_page = resolve_start_page(s, V2_SPIDER_NAMES)
        # query 来自命令行 -a 参数
        spider.query = kwargs.get("query", "") or s.get("V2_QUERY", "")
        # 使用 spider_opened 信号注入初始请求（绕过 Windows 上
        # Scrapy 2.17 start_requests() 生成器不被调用的 bug）
        crawler.signals.connect(spider._on_spider_opened, signal=signals.spider_opened)
        return spider

    def _on_spider_opened(self):
        if not self.query:
            logger.error("v2 爬虫需要搜索关键词! 使用: -a query='关键词'")
            return

        logger.info(
            "v2 爬虫启动: query='%s', start_page=%d, page_size=%d, max_pages=%s",
            self.query, self.start_page, self.page_size,
            self.max_pages or "无限制",
        )
        crawler = self.crawler
        if crawler is not None and crawler.engine is not None:
            crawler.engine.crawl(self._build_page_request(self.start_page))

    def _build_page_request(self, page: int) -> Request:
        payload = {
            "uid": self.user_id,
            "user_id": self.user_id,
            "article_query": {
                "query": self.query,
                "page": page,
                "order_field": self.order_field,
                "order_direction": self.order_direction,
            },
        }

        return Request(
            url=self.api_url,
            method="POST",
            body=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "application/json;charset=UTF-8"},
            callback=self.parse,
            errback=self._on_error,
            meta={"page": page},
            dont_filter=True,
        )

    def parse(self, response: Response) -> Generator[Any, None, None]:
        page = response.meta["page"]
        self.last_page = page  # 供运行日志记录最后爬取页码

        if response.status != 200:
            logger.error("第 %d 页 HTTP %d: %s", page, response.status,
                         response.text[:200])
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error("第 %d 页 JSON 解析失败: %s", page, e)
            return

        if data.get("failure") is True:
            logger.error("第 %d 页 API 错误: %s",
                         page, data.get("cause", "未知"))
            return

        # v2 响应: 扁平结构 {content, totalElements, totalPages, size, number}
        content = data.get("content") or []
        total = data.get("totalElements", 0)
        total_pages = data.get("totalPages", 0)

        # 异常响应检测: 正常响应必有 totalPages > 0
        if total_pages <= 0:
            self._abnormal_count = getattr(self, "_abnormal_count", 0) + 1
            if self._abnormal_count <= 5:
                logger.warning(
                    "第 %d 页响应异常 (totalPages=0)，重试 %d/5",
                    page, self._abnormal_count,
                )
                yield self._build_page_request(page)
            else:
                logger.error("第 %d 页连续异常，停止爬取", page)
            return
        self._abnormal_count = 0

        if page == self.start_page:
            logger.info("首请求成功: total=%d, total_pages=%d, page_size=%d",
                        total, total_pages, len(content))

        for record in content:
            yield self._parse_record(record, page)

        logger.info("第 %d/%d 页完成: %d 条",
                    page, total_pages, len(content))

        # 翻页
        if page >= total_pages:
            logger.info("已到最后一页 (第 %d 页)", page)
            return

        if self.end_page and page >= self.end_page:
            logger.info("已达指定结束页: %d", self.end_page)
            return

        if self.max_pages and page >= (self.start_page + self.max_pages - 1):
            logger.info("已达最大页数限制: %d", self.max_pages)
            return

        yield self._build_page_request(page + 1)

    def _on_error(self, failure):
        page = failure.request.meta.get("page", "?")
        logger.error("第 %s 页网络异常: %s", page, failure.value)

    def _parse_record(self, record: dict, page: int) -> ArticleItem:
        item = record_to_item(record, page, api_version="v2")
        # JSON 导出用: 以查询词派生稳定 query_hash, cur_page = 真实页码
        if self.query:
            item["_query_hash"] = hashlib.md5(
                self.query.strip().encode("utf-8")
            ).hexdigest()
        item["_cur_page"] = page
        return item
