"""
公益学术平台v1 接口爬虫
─────────────────
接口: POST https://pubscholar.cn/hky/open/resources/api/v1/articles
认证: 无需登录 (open API)，仅需签名头

两种模式:
  线性模式 (默认): 按页码遍历单一查询 (lang=C), 受单查询窗口限制 (offset<=10000)
  分桶模式 (V1_BUCKET_MODE=1): 启动时同步调用聚合接口构建分桶计划
    (顶层 collection 固定, 桶内按 year→subject→source 递归切分到每桶 <= 阈值),
    然后逐桶滑动翻页爬取, 突破窗口限制; 桶状态写入 crawl_query_state 表, 支持断点续爬。

启动示例:
  scrapy crawl pubscholar_v1                          # 线性模式 (自动断点续爬)
  scrapy crawl pubscholar_v1 -s V1_BUCKET_MODE=1      # 分桶模式 (北大+南大核心)
  scrapy crawl pubscholar_v1 -s V1_BUCKET_MODE=1 -s V1_BUCKET_MAX_BUCKETS=2   # 测试限爬2桶
"""

import json
import logging
import re
import time
from typing import Any, Generator, Optional

import scrapy
from scrapy import Request, signals
from scrapy.http import Response

from academic_spiders.items import ArticleItem
from academic_spiders.utils.api_client import PubscholarClient, build_payload, default_filters
from academic_spiders.utils.parsers import record_to_item
from academic_spiders.utils.query_plan import (
    PARTITION_ORDER,
    collection_filters,
    compute_max_page,
    dim_values,
)
from academic_spiders.utils.query_state import QueryStateStore
from academic_spiders.utils.resume import V1_SPIDER_NAMES, resolve_start_page

logger = logging.getLogger(__name__)

# 计划构建时聚合接口调用间隔 (秒)
PLAN_AGG_DELAY = 0.2


class PubscholarV1Spider(scrapy.Spider):
    """
    v1 开放接口爬虫 (线性 + 分桶双模式)
    """

    name = "pubscholar_v1"

    # 运行状态 (供 SpiderRunLogExtension 读取)
    last_page = 0
    _abnormal_count = 0

    # 默认配置 (from_crawler 会使用 settings 中的值覆盖)
    api_url = "https://pubscholar.cn/hky/open/resources/api/v1/articles"
    user_id = "0b68c4370e9a43e4ad1690fdd31f643f"
    page_size = 50
    max_pages = None
    start_page = 1
    end_page = None
    year_from = None
    year_to = None

    # 分桶模式配置
    bucket_mode = False
    bucket_collections = ["北大核心", "南大核心"]
    bucket_threshold = 9900
    bucket_depth = 3
    bucket_window = 4
    bucket_concurrency = 2
    bucket_max_buckets = None
    bucket_force_plan = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._store: Optional[QueryStateStore] = None
        self._active_buckets: dict = {}  # query_hash -> 桶运行状态
        self._claimed_buckets = 0        # 本次已领取桶数 (配合 MAX_BUCKETS)
        self._page_seq = 0               # 全局页码序列 (分桶模式 JSON 输出防覆盖)
        self._plan_batch: list = []      # 计划构建期待入库叶子桶缓冲

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        s = crawler.settings
        spider.api_url = s.get("PUBSCHOLAR_V1_URL", spider.api_url)
        spider.user_id = s.get("PUBSCHOLAR_USER_ID", spider.user_id)
        spider.page_size = s.getint("V1_PAGE_SIZE")
        spider.max_pages = s.getint("V1_MAX_PAGES") or None
        spider.end_page = s.getint("V1_END_PAGE") or None
        spider.year_from = s.get("V1_YEAR_FROM")
        spider.year_to = s.get("V1_YEAR_TO")

        # 分桶模式配置
        spider.bucket_mode = s.getbool("V1_BUCKET_MODE", False)
        spider.bucket_threshold = s.getint("V1_BUCKET_THRESHOLD", 9900)
        spider.bucket_depth = s.getint("V1_BUCKET_DEPTH", 3)
        spider.bucket_window = s.getint("V1_BUCKET_WINDOW", 4)
        spider.bucket_concurrency = s.getint("V1_BUCKET_CONCURRENCY", 2)
        raw_collections = s.get("V1_BUCKET_COLLECTIONS", "北大核心,南大核心")
        spider.bucket_collections = [
            c for c in re.split(r"[,，、]", raw_collections) if c
        ]
        raw_max = s.get("V1_BUCKET_MAX_BUCKETS")
        spider.bucket_max_buckets = int(raw_max) if raw_max else None
        spider.bucket_force_plan = s.getbool("V1_BUCKET_FORCE_PLAN", False)

        if not spider.bucket_mode:
            # 线性模式: 起始页 = 显式指定 > 自动断点续爬 > 默认 1
            raw_start = s.get("V1_START_PAGE")
            if raw_start:
                spider.start_page = max(int(raw_start), 1)
            else:
                spider.start_page = resolve_start_page(s, V1_SPIDER_NAMES)

        # 使用 spider_opened 信号注入初始请求 (绕过 Windows 上
        # Scrapy 2.17 start_requests() 生成器不被调用的 bug)
        crawler.signals.connect(spider._on_spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(spider._on_spider_closed, signal=signals.spider_closed)
        return spider

    # ═══════════════════════════════════════════════════════════
    # 启动
    # ═══════════════════════════════════════════════════════════

    def _on_spider_opened(self):
        crawler = self.crawler
        if crawler is None or crawler.engine is None:
            return

        if self.bucket_mode:
            self._store = QueryStateStore(crawler.settings)
            self._store.mark_interrupted()
            logger.info(
                "pubscholar_v1 [分桶模式] 启动: collections=%s, threshold=%d, "
                "depth=%d, window=%d, concurrency=%d, max_buckets=%s, page_size=%d",
                self.bucket_collections, self.bucket_threshold, self.bucket_depth,
                self.bucket_window, self.bucket_concurrency,
                self.bucket_max_buckets or "全部", self.page_size,
            )
            self._build_plan_and_start()
            return

        logger.info(
            "pubscholar_v1 start crawling: start_page=%d, page_size=%d, max_pages=%s, "
            "year_range=%s-%s",
            self.start_page, self.page_size,
            self.max_pages or "No Limit",
            self.year_from or "None", self.year_to or "None",
        )
        crawler.engine.crawl(self._build_page_request(self.start_page))

    def _on_spider_closed(self, spider=None, reason=None):
        """释放查询状态持久连接"""
        if self._store is not None:
            self._store.close()

    # ═══════════════════════════════════════════════════════════
    # 线性模式 (原有逻辑)
    # ═══════════════════════════════════════════════════════════

    def _build_page_request(self, page: int) -> Request:
        """构造分页 POST 请求 (线性模式基础查询)"""
        payload = build_payload(
            self._linear_filters(), page, self.page_size, self.user_id
        )
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

    def _linear_filters(self) -> dict:
        """线性模式查询参数: lang 固定中文 C, 其余为空"""
        return default_filters(lang="C")

    def parse(self, response: Response) -> Generator[Any, None, None]:
        """线性模式: 解析 API 响应, 提取文献列表并翻页"""
        page = response.meta["page"]
        self.last_page = page  # 供运行日志记录最后爬取页码

        # 检查 HTTP 状态
        if response.status != 200:
            logger.error(
                "第 %d 页请求失败: HTTP %d, body=%s",
                page, response.status, response.text[:200],
            )
            return

        # 解析 JSON
        try:
            data = json.loads(response.text)
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
        is_last = data.get("is_last", False)  # 默认 False, 避免缺字段误判为最后一页
        total_pages = data.get("total_pages", 0)

        # 异常响应检测: 正常响应必有 total_pages > 0。
        # total_pages=0 通常是 API 限流/风控返回的空响应, 而非真正的最后一页。
        if total_pages <= 0:
            self._abnormal_count = getattr(self, "_abnormal_count", 0) + 1
            if self._abnormal_count <= 5:
                logger.warning(
                    "第 %d 页响应异常 (total_pages=0, content=%d 条)，"
                    "重试 %d/5 (疑似 API 限流)",
                    page, len(content), self._abnormal_count,
                )
                yield self._build_page_request(page)  # 重试当前页
            else:
                logger.error(
                    "第 %d 页连续异常 %d 次，停止爬取 "
                    "(可能原因: API 限流 / Cookie 过期)",
                    page, self._abnormal_count,
                )
            return
        self._abnormal_count = 0

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
        # ① API 自然结束 (返回 is_last=true)
        if is_last:
            logger.info("已到最后一页 (第 %d 页)，爬取结束", page)
            return

        # ② 绝对结束页限制 (用户指定 V1_END_PAGE)
        if self.end_page and page >= self.end_page:
            logger.info(
                "已达指定结束页: end_page=%d, current_page=%d",
                self.end_page, page,
            )
            return

        # ③ 页数限制 (相对值, 用户指定 V1_MAX_PAGES)
        if self.max_pages and page >= (self.start_page + self.max_pages - 1):
            logger.info(
                "已达最大页数限制: max_pages=%d, current_page=%d",
                self.max_pages, page,
            )
            return

        yield self._build_page_request(page + 1)

    def _on_error(self, failure):
        """线性模式: 请求异常回调"""
        request = failure.request
        page = request.meta.get("page", "?")
        logger.error(
            "第 %s 页网络异常: %s", page, failure.value,
        )

    # ═══════════════════════════════════════════════════════════
    # 分桶模式: 计划构建 (同步 requests, 规避聚合接口在 Scrapy 下载器中的挂起问题)
    # ═══════════════════════════════════════════════════════════

    def _build_plan_and_start(self):
        """构建分桶计划 (阻塞 ~1-3 分钟), 然后启动桶爬取"""
        if (not self.bucket_force_plan
                and self._store.plan_exists(self.bucket_collections,
                                            self.bucket_threshold, self.bucket_depth)):
            logger.info(
                "检测到已有完整分桶计划, 跳过重建 (续爬模式). "
                "如需重建请设置 V1_BUCKET_FORCE_PLAN=1",
            )
            self._try_dispatch_buckets()
            return

        client = PubscholarClient(timeout=30)
        t0 = time.time()
        self._plan_count = 0
        plan_ok = True
        try:
            for collection in self.bucket_collections:
                filters = collection_filters(collection)
                try:
                    agg = client.fetch_aggregations(filters)
                except Exception as e:
                    logger.error("聚合请求失败 (collection=%s): %s", collection, e)
                    plan_ok = False
                    continue
                # 根节点 total: 取 collection 维度中该 collection 的计数
                root_total = next(
                    (v for k, v in dim_values(agg, "collection") if k == collection), 0
                )
                if root_total <= 0:
                    root_total = sum(v for _, v in dim_values(agg, "year"))
                logger.info(
                    "构建分桶计划: collection=%s, root_total=%d",
                    collection, root_total,
                )
                self._plan_recurse(client, filters, agg, 0, collection, root_total)
        finally:
            self._flush_plan_batch()
            logger.info(
                "分桶计划构建完成, 耗时 %.1fs, 叶子桶 %d 个",
                time.time() - t0, self._plan_count,
            )
        if plan_ok:
            self._store.plan_mark(self.bucket_collections, self.bucket_threshold,
                                  self.bucket_depth, self._plan_count)
        self._try_dispatch_buckets()

    def _flush_plan_batch(self):
        """将计划构建期累积的叶子桶批量入库"""
        if self._plan_batch:
            self._store.insert_many(self._plan_batch)
            self._plan_batch = []

    def _push_leaf(self, filters: dict, total: int, collection: str):
        """累积一个叶子桶 (按阈值批量入库)"""
        max_page = compute_max_page(total, self.page_size, self.bucket_threshold)
        self._plan_count += 1
        self._plan_batch.append({
            "filters": dict(filters),
            "total": total,
            "max_page": max_page,
            "page_size": self.page_size,
            "collection": collection,
        })
        logger.debug(
            "叶子桶: total=%d, max_page=%d, filters=%s",
            total, max_page, {k: v for k, v in filters.items() if v},
        )
        if len(self._plan_batch) >= 500:
            self._flush_plan_batch()

    def _plan_recurse(self, client: PubscholarClient, filters: dict, agg: dict,
                      depth: int, collection: str, total: int):
        """递归切分: 叶子桶入库, 非叶子取子维度聚合后递归"""
        if total <= 0:
            return

        can_split = (depth + 1) < self.bucket_depth and depth < len(PARTITION_ORDER)
        if total <= self.bucket_threshold or not can_split:
            self._push_leaf(filters, total, collection)
            return

        dim = PARTITION_ORDER[depth]
        values = dim_values(agg, dim)
        if not values:
            logger.warning(
                "节点无法切分 (dim=%s 无聚合值), 按超大叶子处理: total=%d", dim, total,
            )
            self._push_leaf(filters, total, collection)
            return

        child_sum = sum(v for _, v in values)
        logger.info(
            "切分节点: dim=%s, total=%d, 子桶数=%d, 计数和=%d (覆盖率 %.1f%%)",
            dim, total, len(values), child_sum,
            (child_sum / total * 100) if total else 0,
        )

        for key, val in values:
            if val <= 0:
                continue
            child_filters = dict(filters)
            child_filters[dim] = key
            child_depth = depth + 1
            can_split_child = (
                (child_depth + 1) < self.bucket_depth
                and child_depth < len(PARTITION_ORDER)
            )
            if val <= self.bucket_threshold or not can_split_child:
                self._push_leaf(child_filters, val, collection)
                continue
            time.sleep(PLAN_AGG_DELAY)
            try:
                child_agg = client.fetch_aggregations(child_filters)
            except Exception as e:
                logger.warning(
                    "子节点聚合请求失败, 按超大叶子处理: filters=%s, err=%s",
                    {k: v for k, v in child_filters.items() if v}, e,
                )
                self._push_leaf(child_filters, val, collection)
                continue
            self._plan_recurse(client, child_filters, child_agg, child_depth,
                               collection, val)

    # ═══════════════════════════════════════════════════════════
    # 分桶模式: 桶调度
    # ═══════════════════════════════════════════════════════════

    def _try_dispatch_buckets(self):
        """填满并发桶数; 无活动桶且计划完成则结束爬虫"""
        while len(self._active_buckets) < self.bucket_concurrency:
            if not self._claim_and_start_bucket():
                break
        if not self._active_buckets:
            summary = self._store.summary() if self._store else {}
            if self.bucket_max_buckets is not None and self._claimed_buckets >= self.bucket_max_buckets:
                logger.info("已达桶数上限 (%d), 结束爬取. 状态统计: %s",
                            self.bucket_max_buckets, summary)
            else:
                logger.info("所有查询桶处理完毕, 结束爬取. 状态统计: %s", summary)
            self.crawler.engine.close_spider(self, reason="finished")

    def _claim_and_start_bucket(self) -> bool:
        """领取一个 pending 桶并启动其翻页"""
        if self._store is None:
            return False
        if self.bucket_max_buckets is not None and self._claimed_buckets >= self.bucket_max_buckets:
            return False

        row = self._store.claim_next()
        if row is None:
            return False

        self._claimed_buckets += 1
        qh = row["query_hash"]
        max_page = int(row["max_page"])
        if max_page <= 0:
            self._store.mark_done(qh, "completed")
            return True

        state = {
            "filters": json.loads(row["query_params"]),
            "total": int(row["total"]),
            "max_page": max_page,
            "next_issue": 1,
            "in_flight": 0,
            "retries": 0,
            "items": 0,
            "done": False,
        }
        self._active_buckets[qh] = state
        self._issue_pages(qh, state)
        logger.info(
            "开始爬取桶: qhash=%s, total=%d, max_page=%d, filters=%s",
            qh[:8], state["total"], max_page,
            {k: v for k, v in state["filters"].items() if v},
        )
        return True

    def _issue_pages(self, qh: str, state: dict):
        """滑动窗口: 保持桶内 in_flight 不超过 window"""
        crawler = self.crawler
        if crawler is None or crawler.engine is None:
            return
        while (state["in_flight"] < self.bucket_window
               and state["next_issue"] <= state["max_page"]):
            page = state["next_issue"]
            state["next_issue"] += 1
            state["in_flight"] += 1
            crawler.engine.crawl(self._bucket_page_request(qh, state["filters"], page))

    def _bucket_page_request(self, qh: str, filters: dict, page: int) -> Request:
        """构造桶内分页请求"""
        payload = build_payload(filters, page, self.page_size, self.user_id)
        return Request(
            url=self.api_url,
            method="POST",
            body=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "application/json;charset=UTF-8"},
            callback=self.parse_bucket_page,
            errback=self._on_bucket_error,
            meta={"bucket_hash": qh, "page": page},
            dont_filter=True,
        )

    # ═══════════════════════════════════════════════════════════
    # 分桶模式: 桶内翻页解析
    # ═══════════════════════════════════════════════════════════

    def parse_bucket_page(self, response: Response) -> Generator[Any, None, None]:
        """解析桶内一页: 产出 Item, 滑动翻页, 桶完成/失败时调度下一桶"""
        qh = response.meta["bucket_hash"]
        page = response.meta["page"]
        state = self._active_buckets.get(qh)
        if state is None or state.get("done"):
            logger.warning("收到未知/已结束桶响应: qhash=%s page=%d", qh[:8], page)
            return
        state["in_flight"] -= 1

        # ── 失败处理 ──
        if response.status != 200:
            self._bucket_page_failed(qh, state, page, f"HTTP {response.status}")
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            self._bucket_page_failed(qh, state, page, f"JSON解析失败: {e}")
            return

        if isinstance(data, dict) and data.get("failure") is True:
            cause = data.get("cause", "")
            logger.error(
                "桶 %s 第 %d 页 API 业务错误: %s",
                qh[:8], page, cause,
            )
            # Cookie 过期/权限等业务错误 → 立即停止整个爬虫
            self.crawler.engine.close_spider(self, reason="api_failure")
            return

        content = data.get("content") or []
        is_last = data.get("is_last", False)
        total_pages = data.get("total_pages", 0)

        # 异常响应 (窗口超限/限流): total_pages=0 且内容空
        if total_pages <= 0:
            self._abnormal_count = getattr(self, "_abnormal_count", 0) + 1
            if self._abnormal_count <= 5:
                logger.warning(
                    "桶 %s 第 %d 页响应异常 (total_pages=0), 重试 %d/5",
                    qh[:8], page, self._abnormal_count,
                )
                state["in_flight"] += 1
                self.crawler.engine.crawl(
                    self._bucket_page_request(qh, state["filters"], page)
                )
                return
            self._bucket_failed(qh, state, f"连续异常响应 {self._abnormal_count} 次")
            return
        self._abnormal_count = 0

        # ── 数据产出 ──
        self.last_page = page
        seq = self._page_seq
        self._page_seq += 1
        for record in content:
            yield self._parse_record(record, seq)
        state["items"] += len(content)
        state["retries"] = 0
        self._store.update_progress(qh, page, len(content))

        logger.info(
            "桶 %s 第 %d/%d 页完成: %d 条, 桶内累计 %d 条",
            qh[:8], page, state["max_page"], len(content), state["items"],
        )

        # ── 翻页 ──
        if is_last or page >= state["max_page"]:
            self._bucket_done(qh, state)
            return
        self._issue_pages(qh, state)

    def _bucket_page_failed(self, qh: str, state: dict, page: int, reason: str):
        """单页失败: 重试 <=3 次, 否则整桶失败"""
        state["retries"] = state.get("retries", 0) + 1
        if state["retries"] <= 3:
            logger.warning(
                "桶 %s 第 %d 页失败 (%s), 重试 %d/3",
                qh[:8], page, reason, state["retries"],
            )
            state["in_flight"] += 1
            self.crawler.engine.crawl(self._bucket_page_request(qh, state["filters"], page))
            return
        self._bucket_failed(qh, state, reason)

    def _on_bucket_error(self, failure):
        """桶内请求网络异常"""
        request = failure.request
        qh = request.meta.get("bucket_hash")
        page = request.meta.get("page")
        state = self._active_buckets.get(qh)
        if state is None:
            return
        state["in_flight"] -= 1
        self._bucket_page_failed(qh, state, page, str(failure.value)[:100])

    def _bucket_done(self, qh: str, state: dict):
        """桶完成: 标记状态并调度下一桶"""
        if state.get("done"):
            return
        state["done"] = True
        self._active_buckets.pop(qh, None)
        self._store.mark_done(qh, "completed")
        logger.info(
            "桶完成: qhash=%s, 共 %d 条, max_page=%d",
            qh[:8], state["items"], state["max_page"],
        )
        self._try_dispatch_buckets()

    def _bucket_failed(self, qh: str, state: dict, reason: str):
        """桶失败: 标记失败并调度下一桶"""
        if state.get("done"):
            return
        state["done"] = True
        self._active_buckets.pop(qh, None)
        self._store.mark_done(qh, "failed", reason)
        logger.error("桶失败: qhash=%s, 原因=%s", qh[:8], reason)
        self._try_dispatch_buckets()

    # ── 字段提取 ─────────────────────────────────────────────

    def _parse_record(self, record: dict, page: int) -> ArticleItem:
        return record_to_item(record, page, api_version="v1")
