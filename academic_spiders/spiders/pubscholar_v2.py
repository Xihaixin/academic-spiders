"""
慧科研 v2 接口爬虫
─────────────────
接口: POST https://scholarin.cn/hky/api/v2/resources/article
认证: 需要登录 Cookie (pub_ticket / JSESSIONID)
功能: 按关键词搜索文献，支持自动翻页
"""

import json
import logging
from typing import Any, Generator

import scrapy
from scrapy import Request
from scrapy.http import Response

from academic_spiders.items import ArticleItem

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

    # 默认配置
    api_url = "https://scholarin.cn/hky/api/v2/resources/article"
    user_id = "c9ca380e54f3455ca27bdeb6f921f7b0"
    page_size = 20
    max_pages = None
    start_page = 1
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
        spider.start_page = max(s.getint("V2_START_PAGE"), 1)
        # query 来自命令行 -a 参数
        spider.query = kwargs.get("query", "") or s.get("V2_QUERY", "")
        return spider

    def start_requests(self) -> Generator[Request, None, None]:
        if not self.query:
            logger.error("v2 爬虫需要搜索关键词! 使用: -a query='关键词'")
            return

        logger.info(
            "v2 爬虫启动: query='%s', start_page=%d, page_size=%d, max_pages=%s",
            self.query, self.start_page, self.page_size,
            self.max_pages or "无限制",
        )
        yield self._build_page_request(self.start_page)

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

        if response.status != 200:
            logger.error("第 %d 页 HTTP %d: %s", page, response.status,
                         response.text[:200])
            return

        try:
            data = response.json()
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

        if self.max_pages and page >= (self.start_page + self.max_pages - 1):
            logger.info("已达最大页数限制: %d", self.max_pages)
            return

        yield self._build_page_request(page + 1)

    def _on_error(self, failure):
        page = failure.request.meta.get("page", "?")
        logger.error("第 %s 页网络异常: %s", page, failure.value)

    def _parse_record(self, record: dict, page: int) -> ArticleItem:
        """将 v2 API 记录转为 ArticleItem

        v2 字段映射:
          id → article_md5
          title → title
          abstracts / abstracts_cn → abstracts
          author[] → author_names
          authors[] → authors
          source → source
          date → date
          doi → doi
          keywords[] → key_words
          article_type → article_type
          citation_count, download_count → (忽略, 非重点字段)
          free → is_free
        """
        return ArticleItem(
            _page=page,
            article_md5=record.get("id", ""),
            title=record.get("title", ""),
            abstracts=(record.get("abstracts_cn")
                       or record.get("abstracts")
                       or record.get("abstracts_en")
                       or ""),
            key_words=record.get("keywords", []),
            author_names=record.get("author", []),
            source=record.get("source", ""),
            volume=record.get("volume", ""),
            issue=record.get("issue", ""),
            first_page=record.get("first_page", ""),
            last_page=record.get("last_page", ""),
            date=record.get("date", ""),
            year=self._parse_year(record.get("date", "")),
            doi=record.get("doi", ""),
            cstr=record.get("cstr", ""),
            type=record.get("type", ""),
            article_type=record.get("article_type", ""),
            lang="zh",
            cn_type=record.get("cn_type", ""),
            is_free=record.get("free", False) or record.get("is_free", False),
            links=record.get("links", []),
            authors=record.get("authors", []),
            extend_entity=record.get("extendEntity", {}),
            semantic_entities=record.get("semantic_entities", {}),
            source_list=record.get("source_list", []),
            license=record.get("license", ""),
            local_links=record.get("local_links", []),
            attachments=record.get("attachments", []),
            degree=record.get("degree", ""),
            major=record.get("major", ""),
            school=record.get("school", []),
            tutor=record.get("tutor", []),
            graduation_institution=record.get("graduation_institution", []),
        )

    @staticmethod
    def _parse_year(date_str: str) -> int:
        """从日期字符串提取年份"""
        if not date_str:
            return None
        try:
            return int(date_str[:4])
        except (ValueError, TypeError):
            return None
