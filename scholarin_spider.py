"""
慧科研 (scholarin.cn) 论文数据爬虫

破解了 API 签名反爬机制，支持按关键词搜索论文并自动翻页。
"""

import hashlib
import random
import time
import json
import csv
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class ScholarInSpider:
    """慧科研网站爬虫，自动处理签名加密和翻页"""

    # 从 JS 逆向提取的密钥（qI5z 模块 _16 变量）
    SECRET = "6m6pingbinwaktg227gngifoocrfbo95"

    # 从 JS 逆向提取的 App ID（qI5z 模块 d 变量）
    APP_ID = "a9844cf83a78c1cd9cd96f08c9850e2d"

    # API 基础地址 (o = "https://" + location.host + "/hky")
    BASE_URL = "https://scholarin.cn/hky"
    ARTICLE_API = "/api/v2/resources/article"
    HOME_PAGE = "https://scholarin.cn/explore"

    # 允许的排序字段
    ORDER_FIELDS = {
        "pub_date": "pub_date_sort",
        "relevance": "relevance",
        "citation": "citation_count",
    }

    # 允许的排序方向
    ORDER_DIRECTIONS = ("desc", "asc")

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        min_delay: float = 1.0,
        max_delay: float = 2.0,
        proxy: Optional[str] = None,
        no_proxy: bool = False,
        cookies: Optional[str] = None,
        uid: Optional[str] = None,
    ):
        """
        :param timeout: 请求超时时间（秒）
        :param max_retries: 最大重试次数
        :param min_delay: 请求最小间隔（秒）
        :param max_delay: 请求最大间隔（秒）
        :param proxy: HTTP 代理地址，如 "http://127.0.0.1:7890"
        :param no_proxy: 设为 True 禁用所有代理（忽略系统环境变量）
        :param cookies: Cookie 字符串（从浏览器 DevTools 复制），
                        格式: "name1=value1; name2=value2"
        :param uid: 用户 UID，可从浏览器请求中获取，
                    不提供则使用默认 App ID
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_delay = min_delay
        self.max_delay = max_delay

        self.session = requests.Session()

        # 代理配置
        if no_proxy:
            self.session.trust_env = False
            self.proxies = None
            logger.info("已禁用代理，使用直连模式")
        elif proxy:
            self.session.trust_env = False
            self.proxies = {"http": proxy, "https": proxy}
            logger.info("使用代理: %s", proxy)
        else:
            self.proxies = None

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                # 关键：模拟浏览器 Sec-Fetch 头，服务端用此判断是否为同源请求
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                # 注意：网站设置了 <meta name=referrer content=never>
                # 所以不发送 Referer 头
            }
        )

        # 处理 Cookie（从浏览器复制的字符串）
        if cookies:
            self._load_cookies(cookies)

        # UID 优先使用传入值，否则使用 App ID
        self._uid = uid or self.APP_ID
        self._xsrf_token: Optional[str] = None
        self._session_initialized = False

        # 从 Cookie 中提取 XSRF-TOKEN
        for cookie in self.session.cookies:
            if cookie.name == "XSRF-TOKEN":
                self._xsrf_token = cookie.value
                logger.info("从 Cookie 中提取到 XSRF-TOKEN")

    def _load_cookies(self, cookie_string: str):
        """加载 Cookie 字符串到 session"""
        # 支持多种格式：
        # 1. "name1=value1; name2=value2"
        # 2. 直接从浏览器复制的完整 Cookie 字符串
        for item in cookie_string.split(";"):
            item = item.strip()
            if "=" in item:
                name, _, value = item.partition("=")
                self.session.cookies.set(name.strip(), value.strip())
        logger.info("已加载 %d 个 Cookie", len(self.session.cookies))

    # ── 签名生成 ──────────────────────────────────────────

    @staticmethod
    def _generate_nonce(length: int = 6) -> str:
        """
        生成随机 nonce（6 位大写字母数字混合字符串）。
        模拟 JS: Math.random().toString(36).substr(2).toUpperCase()
        """
        chars = []
        while len(chars) < length:
            # JS: Math.random().toString(36).substr(2)
            # Python: 36 进制随机数去掉 "0." 前缀
            rand_str = (
                str(random.random())
                if random.random() > 0.5
                else hex(random.getrandbits(64))
            )
            # 生成类似 JS 的 base36 效果
            rand_val = int(random.random() * 1e18)
            base36 = ""
            temp = rand_val
            alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
            while temp > 0 and len(base36) < 15:
                base36 = alphabet[temp % 36] + base36
                temp //= 36
            for ch in base36.upper():
                if ch.isalnum():
                    chars.append(ch)
                    if len(chars) >= length:
                        break
        return "".join(chars[:length])

    @classmethod
    def _generate_signature(cls, timestamp: str, nonce: str) -> str:
        """
        生成 SHA1 签名。
        算法: SHA1(sorted([secret, timestamp, nonce]).join(""))
        """
        parts = sorted([cls.SECRET, timestamp, nonce])
        raw = "".join(parts)
        return hashlib.sha1(raw.encode()).hexdigest()

    # ── 请求头构建 ────────────────────────────────────────

    def _build_headers(self, extra_headers: dict = None) -> dict:
        """构建带有签名信息的请求头"""
        timestamp = str(int(time.time() * 1000))
        nonce = self._generate_nonce()
        signature = self._generate_signature(timestamp, nonce)

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://scholarin.cn",
            "nonce": nonce,
            "timestamp": timestamp,
            "signature": signature,
            "x-finger": signature,
        }

        # 携带 XSRF Token（如果有的话）
        if self._xsrf_token:
            headers["X-XSRF-TOKEN"] = self._xsrf_token

        if extra_headers:
            headers.update(extra_headers)

        return headers

    # ── Session 初始化 ────────────────────────────────────

    def init_session(self, force: bool = False):
        """
        访问首页获取必要的 Cookie（XSRF-TOKEN）和 uid。
        :param force: 是否强制重新初始化
        """
        if self._session_initialized and not force:
            return

        logger.info("正在初始化 session，访问首页获取 Cookie...")

        try:
            resp = self.session.get(
                self.HOME_PAGE,
                timeout=self.timeout,
                headers=self._build_headers(),
                proxies=self.proxies,
            )
            resp.raise_for_status()

            # 从 Cookie 中提取 XSRF-TOKEN
            for cookie in self.session.cookies:
                if cookie.name == "XSRF-TOKEN":
                    self._xsrf_token = cookie.value
                    logger.debug("获取到 XSRF-TOKEN: %s...", self._xsrf_token[:10])
                    break

            if not self._xsrf_token:
                logger.warning("未获取到 XSRF-TOKEN cookie")

            # 尝试从页面中提取 uid
            # uid 可能在 JS 中或由首次 API 调用返回
            self._session_initialized = True
            logger.info("Session 初始化完成")

        except requests.RequestException as e:
            logger.warning("Session 初始化失败: %s，将尝试直接请求 API", e)
            self._session_initialized = True  # 仍然标记，让后续请求自行处理

    # ── API 请求 ─────────────────────────────────────────

    def _request_with_retry(self, url: str, payload: dict) -> dict:
        """
        带重试机制的 POST 请求。
        :returns: API 响应的 JSON 数据
        """
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                headers = self._build_headers()
                resp = self.session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                    proxies=self.proxies,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    # 检查业务错误码
                    # 成功: code in (0, 200) 或 failure=false 或 没有错误标识
                    if data.get("failure") is True:
                        error_msg = data.get("cause", data.get("message", "未知错误"))
                        logger.warning(
                            "API 返回错误 (attempt %d/%d): %s",
                            attempt,
                            self.max_retries,
                            error_msg,
                        )
                        if attempt < self.max_retries:
                            time.sleep(2 ** attempt)
                        continue
                    elif data.get("code") in (0, 200) or "data" in data or data.get("failure") is False:
                        return data
                    elif data.get("code") is None and data.get("failure") is None:
                        # 没有 code 也没有 failure，可能是直接返回的数据
                        return data
                    else:
                        error_msg = data.get("message", data.get("msg", "未知错误"))
                        logger.warning(
                            "API 返回错误 (attempt %d/%d): code=%s, %s",
                            attempt,
                            self.max_retries,
                            data.get("code"),
                            error_msg,
                        )
                        if attempt < self.max_retries:
                            time.sleep(2 ** attempt)
                        continue
                elif resp.status_code == 429:
                    wait = 5 * attempt
                    logger.warning("请求过于频繁，等待 %d 秒...", wait)
                    time.sleep(wait)
                else:
                    # 尝试读取响应体获取错误详情
                    try:
                        resp_body = resp.text[:500]
                    except Exception:
                        resp_body = "(无法读取响应体)"
                    logger.warning(
                        "HTTP %d (attempt %d/%d), 响应: %s",
                        resp.status_code,
                        attempt,
                        self.max_retries,
                        resp_body,
                    )
                    if attempt < self.max_retries:
                        time.sleep(2 ** attempt)

            except requests.Timeout:
                logger.warning("请求超时 (attempt %d/%d)", attempt, self.max_retries)
            except requests.RequestException as e:
                logger.warning("请求异常 (attempt %d/%d): %s", attempt, self.max_retries, e)
                last_error = e

            if attempt < self.max_retries:
                time.sleep(2 ** attempt)

        if last_error:
            raise last_error
        raise RuntimeError(f"请求失败，已达最大重试次数 ({self.max_retries})")

    # ── 搜索接口 ─────────────────────────────────────────

    def search_articles(
        self,
        query: str,
        page: int = 1,
        order_field: str = "pub_date",
        order_direction: str = "desc",
        **extra_params,
    ) -> dict:
        """
        搜索论文（单页）。

        :param query: 搜索关键词
        :param page: 页码（从 1 开始）
        :param order_field: 排序字段: pub_date / relevance / citation
        :param order_direction: 排序方向: desc / asc
        :param extra_params: 其他 article_query 参数
        :return: API 响应的 dict，包含 data.records 列表和 data.total 总数
        """
        if not self._session_initialized:
            self.init_session()

        # 标准化排序字段
        mapped_field = self.ORDER_FIELDS.get(order_field, order_field)
        if order_direction not in self.ORDER_DIRECTIONS:
            order_direction = "desc"

        article_query = {
            "query": query,
            "page": page,
            "order_field": mapped_field,
            "order_direction": order_direction,
            **extra_params,
        }

        # uid 和 user_id 必须带上（API 需要认证）
        payload = {
            "uid": self._uid,
            "user_id": self._uid,
            "article_query": article_query,
        }

        url = f"{self.BASE_URL}{self.ARTICLE_API}"
        logger.info("搜索 '%s' 第 %d 页...", query, page)

        # 请求间隔
        delay = random.uniform(self.min_delay, self.max_delay)
        time.sleep(delay)

        return self._request_with_retry(url, payload)

    @staticmethod
    def _extract_pagination(data: dict) -> tuple:
        """从 API 响应中提取分页信息 (records, total, page_size)

        v2 接口响应是扁平结构:
        {content: [...], totalElements: N, totalPages: N, size: N, number: N}
        """
        # v2 接口：content 直接在顶层
        if "content" in data:
            return (
                data.get("content") or [],
                data.get("totalElements") or data.get("total") or 0,
                data.get("size") or 10,
            )
        # 兼容嵌套在 data 下的情况
        inner = data.get("data", data)
        if isinstance(inner, list):
            return inner, len(inner), len(inner)
        records = inner.get("records") or inner.get("content") or []
        total = inner.get("totalElements") or inner.get("total") or 0
        page_size = inner.get("size") or 10
        return records, total, page_size

    def search_all(
        self,
        query: str,
        max_pages: Optional[int] = None,
        order_field: str = "pub_date",
        order_direction: str = "desc",
        **extra_params,
    ) -> list:
        """
        搜索论文并自动翻页获取所有结果。

        :param query: 搜索关键词
        :param max_pages: 最大页数限制（None 表示获取全部）
        :param order_field: 排序字段
        :param order_direction: 排序方向
        :param extra_params: 其他 article_query 参数
        :return: 论文数据列表
        """
        all_records = []

        # 先请求第一页，获取总数
        first_page = self.search_articles(
            query=query,
            page=1,
            order_field=order_field,
            order_direction=order_direction,
            **extra_params,
        )

        records, total, page_size = self._extract_pagination(first_page)
        all_records.extend(records)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        logger.info(
            "搜索 '%s': 共 %d 条结果, %d 页, 每页 %d 条",
            query, total, total_pages, page_size,
        )

        actual_max = total_pages
        if max_pages is not None:
            actual_max = min(max_pages, total_pages)

        # 获取剩余页面
        for page in range(2, actual_max + 1):
            try:
                result = self.search_articles(
                    query=query,
                    page=page,
                    order_field=order_field,
                    order_direction=order_direction,
                    **extra_params,
                )
                page_records, _, _ = self._extract_pagination(result)
                all_records.extend(page_records)
                logger.info(
                    "第 %d/%d 页完成，已获取 %d 条",
                    page, actual_max, len(all_records),
                )
            except Exception as e:
                logger.error("获取第 %d 页失败: %s", page, e)
                # 继续尝试下一页
                continue

        logger.info("搜索完成，共获取 %d 条记录", len(all_records))
        return all_records

    # ── 数据提取 ─────────────────────────────────────────

    @staticmethod
    def extract_article_info(record: dict) -> dict:
        """从原始 API 记录中提取关键字段"""
        return {
            "article_id": record.get("id", ""),
            "title": record.get("title", ""),
            "title_en": record.get("title_en", ""),
            "authors": ", ".join(record.get("author", [])),
            "authors_detail": ", ".join(
                a.get("name", "") for a in record.get("authors", [])
            ),
            "institutions": ", ".join(record.get("institution", [])),
            "source": record.get("source", ""),
            "source_en": record.get("source_en", ""),
            "pub_date": record.get("date", ""),
            "doi": record.get("doi", ""),
            "abstract": record.get("abstracts", ""),
            "abstract_cn": record.get("abstracts_cn", ""),
            "abstract_en": record.get("abstracts_en", ""),
            "keywords": ", ".join(record.get("keywords", [])),
            "article_type": record.get("article_type", ""),
            "citation_count": record.get("citation_count", 0),
            "download_count": record.get("download_count", 0),
            "free": record.get("free", False),
        }

    # ── 保存数据 ─────────────────────────────────────────

    @staticmethod
    def save_to_json(data: list, filename: str, indent: int = 2):
        """保存为 JSON 文件"""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        logger.info("已保存 %d 条记录到 %s", len(data), filename)

    @staticmethod
    def save_to_csv(data: list, filename: str):
        """保存为 CSV 文件"""
        if not data:
            logger.warning("没有数据可保存")
            return

        fieldnames = list(data[0].keys())
        with open(filename, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        logger.info("已保存 %d 条记录到 %s", len(data), filename)


# ═══════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="慧科研 (scholarin.cn) 论文爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本搜索（需要 Cookie 认证）
  python scholarin_spider.py -q "人工智能" -p 5 --cookies "XSRF-TOKEN=xxx; SESSION=yyy"

  # 从文件加载 Cookie
  python scholarin_spider.py -q "人工智能" -p 5 --cookies-file cookies.txt

  # 配合代理使用
  python scholarin_spider.py -q "机器学习" --all --proxy http://127.0.0.1:7890 --cookies-file cookies.txt

  # 获取全部结果并保存
  python scholarin_spider.py -q "深度学习" --all --format csv -o papers.csv --cookies "..."

获取 Cookie 的方法：
  1. 在浏览器中登录 https://scholarin.cn
  2. 打开 DevTools (F12) -> Network 标签
  3. 在页面上搜索一次
  4. 找到 /hky/api/v2/resources/article 请求
  5. 复制 Request Headers 中的 Cookie 值
  6. 同时也复制请求体中的 uid 值（通过 --uid 传入）
        """,
    )
    parser.add_argument("-q", "--query", required=True, help="搜索关键词")
    parser.add_argument("-p", "--pages", type=int, default=1, help="爬取页数 (默认 1)")
    parser.add_argument("--all", action="store_true", help="获取全部结果")
    parser.add_argument(
        "--sort",
        choices=["pub_date", "relevance", "citation"],
        default="pub_date",
        help="排序方式 (默认 pub_date)",
    )
    parser.add_argument(
        "--order",
        choices=["desc", "asc"],
        default="desc",
        help="排序方向 (默认 desc)",
    )
    parser.add_argument(
        "-o", "--output", default=None, help="输出文件路径 (默认自动生成)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="输出格式 (默认 json)",
    )
    parser.add_argument("--extract", action="store_true", help="提取关键字段后保存")
    parser.add_argument(
        "--delay-min", type=float, default=1.0, help="最小请求间隔秒数 (默认 1.0)"
    )
    parser.add_argument(
        "--delay-max", type=float, default=2.0, help="最大请求间隔秒数 (默认 2.0)"
    )
    parser.add_argument(
        "--retries", type=int, default=3, help="最大重试次数 (默认 3)"
    )
    parser.add_argument("--proxy", default=None, help="HTTP 代理，如 http://127.0.0.1:7890")
    parser.add_argument("--no-proxy", action="store_true", help="禁用代理直连")
    parser.add_argument(
        "--cookies",
        default=None,
        help='Cookie 字符串，格式: "key1=val1; key2=val2"（从浏览器 DevTools 复制）',
    )
    parser.add_argument(
        "--cookies-file",
        default=None,
        help="从文件加载 Cookie（每行一个 cookie 或 cookie 字符串）",
    )
    parser.add_argument("--uid", default=None, help="用户 UID（从浏览器请求中获取）")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细日志")

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # 创建爬虫
    # 处理 Cookie
    cookies = args.cookies
    if args.cookies_file:
        try:
            with open(args.cookies_file, "r", encoding="utf-8") as f:
                cookies = f.read().strip()
        except FileNotFoundError:
            logger.error("Cookie 文件不存在: %s", args.cookies_file)
            return

    spider = ScholarInSpider(
        max_retries=args.retries,
        min_delay=args.delay_min,
        max_delay=args.delay_max,
        proxy=args.proxy,
        no_proxy=args.no_proxy,
        cookies=cookies,
        uid=args.uid,
    )

    # 初始化 session
    spider.init_session()

    # 搜索
    if args.all:
        raw_data = spider.search_all(
            query=args.query,
            order_field=args.sort,
            order_direction=args.order,
        )
    else:
        all_records = []
        for page in range(1, args.pages + 1):
            result = spider.search_articles(
                query=args.query,
                page=page,
                order_field=args.sort,
                order_direction=args.order,
            )
            records, total, _ = spider._extract_pagination(result)
            all_records.extend(records)
            logger.info("第 %d 页: 获取 %d 条 (总共 %d 条)", page, len(records), total)
        raw_data = all_records

    if not raw_data:
        logger.warning("未获取到任何数据！")
        return

    # 提取字段（可选）
    if args.extract:
        output_data = [spider.extract_article_info(r) for r in raw_data]
    else:
        output_data = raw_data

    # 保存
    if args.output:
        filename = args.output
    else:
        safe_query = args.query.replace(" ", "_")[:30]
        ext = "csv" if args.format == "csv" else "json"
        filename = f"scholarin_{safe_query}_{len(output_data)}.{ext}"

    if args.format == "csv":
        spider.save_to_csv(output_data, filename)
    else:
        spider.save_to_json(output_data, filename)


if __name__ == "__main__":
    main()
