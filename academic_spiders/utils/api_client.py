"""
pubscholar v1 API 轻量客户端
──────────────────────────
封装签名头生成、Cookie 注入、聚合/文章两个接口的请求。
供验证脚本 (fetch_aggregations.py / verify_window_limit.py) 与后续分桶爬虫复用。

接口:
  POST /articles/aggregations   获取筛选条件聚合 (各维度可选值 + 计数)
  POST /articles                获取文献分页数据
"""

import logging
from typing import Any, Dict

import requests

from academic_spiders.utils.cookie_config import load_cookie_config
from academic_spiders.utils.signing import build_signature_headers

logger = logging.getLogger(__name__)

BASE_URL = "https://pubscholar.cn/hky/open/resources/api/v1"

# 请求体 aggregations 对象的 11 个筛选项键 (顺序与前端一致)
AGG_FILTER_KEYS = [
    "type", "subject", "year", "keyword", "collection", "lang",
    "source", "correspAuthor", "funding", "institution", "license",
]


def default_filters(lang: str = "C") -> Dict[str, str]:
    """构造默认筛选项: 语言固定为中文 (C), 其余维度为空"""
    return {k: "" for k in AGG_FILTER_KEYS} | {"lang": lang}


def build_payload(filters: Dict[str, str], page: int, size: int, user_id: str) -> Dict[str, Any]:
    """构造 v1 接口统一请求体 (聚合/文章接口共用)"""
    agg = {k: str(filters.get(k, "")) for k in AGG_FILTER_KEYS}
    return {
        "page": page,
        "size": size,
        "order_field": "date",
        "order_direction": "desc",
        "user_id": user_id,
        "lang": "zh",
        "aggregations": agg,
    }


class PubscholarClient:
    """pubscholar v1 接口客户端"""

    def __init__(self, version: str = "v1", timeout: int = 30):
        cfg = load_cookie_config()[version]
        self.secret = cfg["secret"]
        self.finger = cfg["finger"]
        self.user_id = cfg["user_id"]
        self.cookie = cfg["cookie"]
        self.xsrf = cfg["xsrf_token"]
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {
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
            "Cookie": self.cookie,
            "X-XSRF-TOKEN": self.xsrf,
            **build_signature_headers(self.secret, self.finger),
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.post(
            BASE_URL + path, json=payload, headers=self._headers(), timeout=self.timeout
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"JSON 解析失败: {e} | {resp.text[:200]}") from e

    def fetch_aggregations(self, filters: Dict[str, str], page: int = 1, size: int = 10) -> Dict[str, Any]:
        """获取筛选条件聚合: {维度键: {alias, selected_aggregation, aggregations[]}}"""
        return self._post("/articles/aggregations", build_payload(filters, page, size, self.user_id))

    def fetch_articles(self, filters: Dict[str, str], page: int, size: int = 50) -> Dict[str, Any]:
        """获取文章分页: {total, total_pages, is_last, content[]}"""
        return self._post("/articles", build_payload(filters, page, size, self.user_id))
