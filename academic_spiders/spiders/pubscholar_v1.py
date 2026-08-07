"""
慧科研 v1 接口爬虫
─────────────────
接口: POST https://pubscholar.cn/hky/open/resources/api/v1/articles
认证: 无需登录 (open API)，仅需签名头
目标: 按页码遍历获取全部中文文献 (~7400万条)
"""

import json
import logging
from typing import Any, Generator, Optional

import scrapy
from scrapy import Request, signals
from scrapy.http import Response

from academic_spiders.items import ArticleItem

logger = logging.getLogger(__name__)


class PubscholarV1Spider(scrapy.Spider):
    """
    v1 开放接口爬虫

    启动示例:
      scrapy crawl pubscholar_v1

      限制页数:
      scrapy crawl pubscholar_v1 -s V1_MAX_PAGES=10

      断点续爬:
      scrapy crawl pubscholar_v1 -s V1_START_PAGE=1000
    """

    name = "pubscholar_v1"

    # 默认配置（from_crawler 会使用 settings 中的值覆盖）
    api_url = "https://pubscholar.cn/hky/open/resources/api/v1/articles"
    user_id = "0b68c4370e9a43e4ad1690fdd31f643f"
    page_size = 50
    max_pages = None
    start_page = 1
    year_from = None
    year_to = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        s = crawler.settings
        spider.api_url = s.get("PUBSCHOLAR_V1_URL", spider.api_url)
        spider.user_id = s.get("PUBSCHOLAR_USER_ID", spider.user_id)
        spider.page_size = s.getint("V1_PAGE_SIZE")
        spider.max_pages = s.getint("V1_MAX_PAGES") or None
        spider.start_page = max(s.getint("V1_START_PAGE"), 1)
        spider.year_from = s.get("V1_YEAR_FROM")
        spider.year_to = s.get("V1_YEAR_TO")
        # 使用 spider_opened 信号注入初始请求（绕过 Windows 上
        # Scrapy 2.17 start_requests() 生成器不被调用的 bug）
        crawler.signals.connect(spider._on_spider_opened, signal=signals.spider_opened)
        return spider

    def _on_spider_opened(self):
        logger.info(
            "v1 爬虫启动: start_page=%d, page_size=%d, max_pages=%s, "
            "year_range=%s-%s",
            self.start_page, self.page_size,
            self.max_pages or "无限制",
            self.year_from or "无", self.year_to or "无",
        )
        self.crawler.engine.crawl(self._build_page_request(self.start_page))

    def _build_page_request(self, page: int) -> Request:
        """构造分页 POST 请求"""
        payload = {
            "page": page,
            "size": self.page_size,
            "order_field": "date",
            "order_direction": "desc",
            "user_id": self.user_id,
            "lang": "zh",
            "aggregations": {
                "type": "",
                "subject": "",
                "year": "",
                "keyword": "",
                "collection": "",
                "lang": "C",            # 'C' = 中文文献
                "source": "",
                "correspAuthor": "",
                "funding": "",
                "institution": "",
                "license": "",
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
        """解析 API 响应，提取文献列表并翻页"""
        page = response.meta["page"]

        # 检查 HTTP 状态
        if response.status != 200:
            logger.error(
                "第 %d 页请求失败: HTTP %d, body=%s",
                page, response.status, response.text[:200],
            )
            return

        # 解析 JSON
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            logger.error("第 %d 页 JSON 解析失败: %s", page, e)
            return

        # 检查业务错误
        if isinstance(data, dict) and data.get("failure") is True:
            logger.error(
                "第 %d 页 API 业务错误: %s", page,
                data.get("cause", data.get("message", "未知")),
            )
            return

        # 提取文献列表
        content = data.get("content") or []
        total = data.get("total", 0)
        is_last = data.get("is_last", True)
        total_pages = data.get("total_pages", 0)

        if page == self.start_page:
            logger.info(
                "首请求成功: total=%d, total_pages=%d, page_size=%d",
                total, total_pages, len(content),
            )

        # 逐条生成 Item
        for record in content:
            yield self._parse_record(record, page)

        logger.info(
            "第 %d/%d 页完成，获取 %d 条，累计约 %d 条",
            page, total_pages, len(content), page * self.page_size,
        )

        # ── 翻页判断 ────────────────────────────────────────
        if is_last:
            logger.info("已到最后一页 (第 %d 页)，爬取结束", page)
            return

        # 检查 max_pages 限制
        if self.max_pages and page >= (self.start_page + self.max_pages - 1):
            logger.info(
                "已达最大页数限制: max_pages=%d, current_page=%d",
                self.max_pages, page,
            )
            return

        yield self._build_page_request(page + 1)

    def _on_error(self, failure):
        """请求异常回调"""
        request = failure.request
        page = request.meta.get("page", "?")
        logger.error(
            "第 %s 页网络异常: %s", page, failure.value,
        )

    # ── 字段提取 ─────────────────────────────────────────────

    def _parse_record(self, record: dict, page: int) -> ArticleItem:
        """将单条 API 记录转为 ArticleItem"""

        return ArticleItem(
            # 元信息
            _page=page,

            # 核心字段
            article_md5=record.get("id", ""),
            title=record.get("title", ""),
            abstracts=record.get("abstracts", ""),
            key_words=record.get("keywords", []),
            author_names=record.get("author", []),
            source=record.get("source", ""),
            volume=record.get("volume", ""),
            issue=record.get("issue", ""),
            first_page=record.get("first_page", ""),
            last_page=record.get("last_page", ""),
            date=record.get("date", ""),
            year=record.get("year"),
            doi=record.get("doi", ""),
            cstr=record.get("cstr", ""),
            type=record.get("type", ""),
            article_type=record.get("article_type", ""),
            lang="zh",
            cn_type=record.get("cn_type", ""),
            is_free=record.get("is_free", False),
            links=record.get("links", []),

            # 子表数据 (原始 JSON)
            authors=record.get("authors", []),
            extend_entity=record.get("extendEntity", {}),
            semantic_entities=record.get("semantic_entities", {}),
            source_list=record.get("source_list", []),
            license=record.get("license", ""),
            local_links=record.get("local_links", []),
            attachments=record.get("attachments", []),

            # 学位论文信息
            degree=record.get("degree", ""),
            major=record.get("major", ""),
            school=record.get("school", []),
            tutor=record.get("tutor", []),
            graduation_institution=record.get("graduation_institution", []),
        )
