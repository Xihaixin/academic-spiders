"""
聚合分桶模式: 分桶参数与纯函数
─────────────────────────────
分桶策略 (验证结论):
  - collection 顶层固定 (北大核心 / 南大核心), lang 固定中文 C
  - year 是唯一完备划分维度 (计数和 = 100% 总计数)
  - subject 单值但聚合列表被 top-100 截断 (覆盖率 ~92%)
  - 窄上下文内 source 聚合完备 (可用于回收超大桶)
  - 单查询窗口: offset <= 10000 条, 每桶 total <= threshold 可完整爬取
"""

import math
from typing import Dict, List, Tuple

from academic_spiders.utils.api_client import default_filters

# 切分维度顺序 (递归逐级使用)
PARTITION_ORDER = ["year", "subject", "source"]

# 接口单查询窗口上限 (offset, 验证确认: size=50→200页/100→100页/10→1000页)
WINDOW_LIMIT = 10000


def collection_filters(collection: str, lang: str = "C") -> Dict[str, str]:
    """构造某 collection 的根查询参数 (语言固定中文)"""
    filters = default_filters(lang=lang)
    if collection:
        filters["collection"] = collection
    return filters


def dim_values(agg: dict, dim: str) -> List[Tuple[str, int]]:
    """从聚合响应提取某维度的 (origin_key, value) 列表"""
    items = (agg.get(dim) or {}).get("aggregations") or []
    return [(v["origin_key"], int(v.get("value", 0))) for v in items]


def compute_max_page(total: int, size: int, threshold: int) -> int:
    """桶内翻页边界: 不超过窗口页数, 也不超过实际总页数"""
    if total <= 0:
        return 0
    window_pages = max(threshold // size, 1)
    return min(math.ceil(total / size), window_pages)
