"""
抓取 pubscholar v1 aggregations 响应并保存为 JSON 文件
──────────────────────────────────────────────────────
对应需求: 获取 aggregation 请求的响应结果，并使用 json 文件进行保存。

用法示例:
  python fetch_aggregations.py
  python fetch_aggregations.py --collection 北大核心
  python fetch_aggregations.py --collection 北大核心 --year 2020
  python fetch_aggregations.py --all-core        # 北大核心 + 南大核心
  python fetch_aggregations.py --all-core --with-total

--with-total 会额外请求一次 articles 接口, 在 JSON 中标注 total/total_pages。
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from academic_spiders.utils.api_client import PubscholarClient, default_filters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_aggregations")

OUT_DIR = Path("result") / "aggregations"

CORE_COLLECTIONS = ["北大核心", "南大核心"]


def build_tag(filters: Dict[str, str]) -> str:
    """由非空筛选项生成文件名标签"""
    parts = [f"{k}={v}" for k, v in filters.items() if v]
    return "_".join(parts) if parts else "base"


def summarize(agg: Dict[str, object]) -> None:
    """打印聚合响应各维度概览"""
    print(f"\n{'维度':<12} {'别名':<14} {'值个数':>5} {'最小计数':>12} {'最大计数':>12}")
    print("-" * 62)
    for key, item in agg.items():
        if not isinstance(item, dict):
            continue
        items = item.get("aggregations") or []
        values = [v.get("value", 0) for v in items] if items else [0]
        print(
            f"{key:<12} {str(item.get('alias', '')):<14} {len(items):>5} "
            f"{min(values):>12,} {max(values):>12,}"
        )


def fetch_and_save(
    client: PubscholarClient,
    filters: Dict[str, str],
    out_dir: Path,
    with_total: bool = False,
    delay: float = 0.4,
) -> Path:
    """抓取一次聚合响应并保存, 返回保存路径"""
    agg = client.fetch_aggregations(filters)

    if with_total:
        try:
            data = client.fetch_articles(filters, page=1, size=1)
            agg["_meta"] = {
                "total": data.get("total", 0),
                "total_pages": data.get("total_pages", 0),
                "is_last": data.get("is_last", False),
            }
        except Exception as e:
            logger.warning("获取 total 失败: %s", e)

    tag = build_tag(filters)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"aggregations_{tag}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)

    print(f"\n=== 已保存: {out_path}")
    if "_meta" in agg:
        print(f"total={agg['_meta']['total']:,} total_pages={agg['_meta']['total_pages']:,}")
    summarize(agg)
    time.sleep(delay)
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="抓取 pubscholar v1 aggregations 响应并保存为 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--collection", type=str, default=None, help="核心收录 (北大核心/南大核心), 可逗号分隔多个")
    parser.add_argument("--all-core", action="store_true", help="同时抓取 北大核心 + 南大核心")
    parser.add_argument("--type", dest="art_type", type=str, default=None, help="论文类型 (期刊论文/学位论文/...)")
    parser.add_argument("--year", type=str, default=None, help="出版年 (如 2020)")
    parser.add_argument("--subject", type=str, default=None, help="学科分类")
    parser.add_argument("--source", type=str, default=None, help="出版物/来源")
    parser.add_argument("--keyword", type=str, default=None, help="关键词")
    parser.add_argument("--institution", type=str, default=None, help="作者机构")
    parser.add_argument("--funding", type=str, default=None, help="基金资助机构")
    parser.add_argument("--corresp-author", type=str, default=None, help="通讯作者")
    parser.add_argument("--license", type=str, default=None, help="使用许可")
    parser.add_argument("--lang", type=str, default="C", help="语言 (默认 C=中文)")
    parser.add_argument("--out", type=str, default=None, help="输出目录 (默认 result/aggregations)")
    parser.add_argument("--with-total", action="store_true", help="额外请求 articles 接口标注 total")
    return parser.parse_args()


def main():
    args = parse_args()
    client = PubscholarClient()
    out_dir = Path(args.out) if args.out else OUT_DIR

    collections: List[Optional[str]] = []
    if args.all_core:
        collections = list(CORE_COLLECTIONS)
    elif args.collection:
        collections = [c.strip() for c in args.collection.split(",") if c.strip()]
    else:
        collections = [None]

    for coll in collections:
        filters = default_filters(lang=args.lang)
        if coll:
            filters["collection"] = coll
        for key, val in (
            ("type", args.art_type),
            ("year", args.year),
            ("subject", args.subject),
            ("source", args.source),
            ("keyword", args.keyword),
            ("institution", args.institution),
            ("funding", args.funding),
            ("correspAuthor", args.corresp_author),
            ("license", args.license),
        ):
            if val:
                filters[key] = val
        fetch_and_save(client, filters, out_dir, with_total=args.with_total)

    print("\n完成。")


if __name__ == "__main__":
    main()
