"""
pubscholar v1 分桶爬取可行性验证
────────────────────────────────
对应需求:
  1. 再次验证 lang=C, page>200 后的响应情况
  2. 验证使用组合查询参数时, 平台是否仍限制返回数据量 (窗口是否按查询重置)
  3. 聚合计数一致性 (各维度计数之和 ≈ 总计数, 用于分桶完整性)
  4. 聚合维度截断检测 (每上下文最多返回 ~100 个值)
  5. 递归分治可行性预览 (真实调用聚合接口模拟分桶: 桶数/请求数/覆盖率/预估耗时)

用法:
  python verify_window_limit.py                # 全流程
  python verify_window_limit.py --window-only  # 只做窗口探测
  python verify_window_limit.py --plan-only    # 只做分桶预览
  python verify_window_limit.py --threshold 9000
"""

import argparse
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from academic_spiders.utils.api_client import PubscholarClient, default_filters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("verify_window")

# 分治维度顺序: 只使用单值/完备性较好的维度, 避开强重叠的 keyword/institution/funding
PARTITION_ORDER = ["year", "subject", "source", "institution", "type"]

# 中文核心集合 (需求限定)
CORE_COLLECTIONS = ["北大核心", "南大核心"]


def _filters(collection: str = "", extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    f = default_filters(lang="C")
    if collection:
        f["collection"] = collection
    if extra:
        f.update(extra)
    return f


def classify(row: Dict[str, Any]) -> str:
    """判定一次分页探测结果的性质"""
    if row.get("http") == "ERR":
        return "ERR"
    content = row["content"]
    total = row["total"]
    total_pages = row["total_pages"]
    if content == 0 and total == 0:
        return "窗口超限(异常)"
    if content == 0 and total > 0:
        return "自然结束"
    return "正常返回"


def probe_pages(client: PubscholarClient, filters: Dict[str, str], size: int, pages: List[int], delay: float) -> List[Dict[str, Any]]:
    """对一组页码逐页探测, 记录关键字段"""
    rows: List[Dict[str, Any]] = []
    for p in pages:
        try:
            data = client.fetch_articles(filters, page=p, size=size)
            row = {
                "page": p,
                "content": len(data.get("content") or []),
                "total": data.get("total", 0),
                "total_pages": data.get("total_pages", 0),
                "is_last": data.get("is_last", False),
            }
        except Exception as e:
            row = {"page": p, "http": "ERR", "error": str(e)[:100]}
        row["class"] = classify(row)
        rows.append(row)
        time.sleep(delay)
    return rows


def print_probe(label: str, rows: List[Dict[str, Any]]) -> None:
    print(f"\n── {label} ──")
    print(f"{'page':>6} {'content':>7} {'total':>12} {'total_pages':>11} {'is_last':>7} 判定")
    for r in rows:
        if r.get("http") == "ERR":
            print(f"{r['page']:>6}     ERR   {r.get('error','')}")
            continue
        print(
            f"{r['page']:>6} {r['content']:>7} {r['total']:>12,} "
            f"{r['total_pages']:>11,} {str(r['is_last']):>7} {r['class']}"
        )


# ── 1. 窗口探测 ──────────────────────────────────────────────

def run_window_probe(client: PubscholarClient, delay: float) -> None:
    print("\n" + "=" * 70)
    print("【1】分页窗口探测")
    print("=" * 70)

    base = _filters()
    bd = _filters("北大核心")
    bd20 = _filters("北大核心", {"year": "2020"})
    deep = _filters("北大核心", {"year": "2020", "subject": "医药、卫生"})

    # 基础查询不同 page_size 下窗口位置 (判断限制是基于页码还是基于 offset=page*size)
    print_probe("基础查询 lang=C, size=50", probe_pages(client, base, 50, [1, 195, 199, 200, 201], delay))
    print_probe("基础查询 lang=C, size=100 (验证窗口是否随 offset 缩放)", probe_pages(client, base, 100, [99, 100, 101], delay))
    print_probe("基础查询 lang=C, size=10 (验证窗口是否随 offset 缩放)", probe_pages(client, base, 10, [995, 999, 1000, 1001], delay))

    # 组合过滤后窗口是否重置 (核心可行性问题)
    print_probe("北大核心, size=50", probe_pages(client, bd, 50, [1, 199, 200, 201], delay))
    print_probe("北大核心+year=2020, size=50", probe_pages(client, bd20, 50, [1, 200, 201, 250], delay))
    print_probe("北大核心+year=2020+subject=医药卫生, size=50", probe_pages(client, deep, 50, [1, 200, 201, 210], delay))


# ── 2. 计数一致性 ────────────────────────────────────────────

def count_consistency(client: PubscholarClient, label: str, filters: Dict[str, str], dims: List[str], delay: float) -> None:
    print(f"\n── 计数一致性: {label} ──")
    try:
        agg = client.fetch_aggregations(filters)
    except Exception as e:
        print(f"  聚合请求失败: {e}")
        return
    try:
        art = client.fetch_articles(filters, page=1, size=1)
        total = art.get("total", 0)
    except Exception as e:
        print(f"  articles 请求失败: {e}")
        total = 0
    print(f"  articles.total = {total:,}")
    for dim in dims:
        items = agg.get(dim, {}).get("aggregations") or []
        s = sum(v.get("value", 0) for v in items)
        ratio = (s / total) if total else 0
        flag = "✓" if 0.97 <= ratio <= 1.03 else ("⚠ 偏差!" if ratio < 0.9 else "")
        print(f"  聚合[{dim:<12}] 值数={len(items):>4} 计数和={s:>14,}  占比={ratio*100:5.1f}%  {flag}")
    time.sleep(delay)


# ── 3. 截断检测 ──────────────────────────────────────────────

def truncation_check(client: PubscholarClient, delay: float) -> None:
    print("\n" + "=" * 70)
    print("【2】聚合维度截断检测 (每上下文最多返回多少可选值)")
    print("=" * 70)
    contexts: List[Tuple[str, Dict[str, str]]] = [
        ("基础 lang=C", _filters()),
        ("北大核心", _filters("北大核心")),
        ("南大核心", _filters("南大核心")),
    ]
    for label, filters in contexts:
        try:
            agg = client.fetch_aggregations(filters)
        except Exception as e:
            print(f"\n── {label}: 请求失败 {e}")
            continue
        print(f"\n── {label} ──")
        for key, item in agg.items():
            if not isinstance(item, dict):
                continue
            n = len(item.get("aggregations") or [])
            mark = " ⚠接近上限100" if n >= 100 else ""
            print(f"  {key:<12} {n:>4} 个值{mark}")
        time.sleep(delay)


# ── 4. 递归分治可行性预览 ───────────────────────────────────

def build_plan(
    client: PubscholarClient,
    root_filters: Dict[str, str],
    root_total: int,
    order: List[str],
    threshold: int,
    size: int,
    max_nodes: int,
    delay: float,
    max_depth: int = 2,
) -> Dict[str, Any]:
    """递归分治预览: 真实调用聚合接口逐层切分, 直到叶子桶 <= threshold 或达到 max_depth

    max_depth 限制切分层数 (默认 2: year→subject)。
    超过 threshold 又无法再切的桶记为 oversized, 实际爬取时要么由下一维度再切分,
    要么接受只爬窗口前 10k 条 (部分覆盖)。
    """
    leaves: List[Dict[str, Any]] = []
    oversized: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    nodes = 0
    api_calls = 0
    stack: List[Tuple[Dict[str, str], int, int]] = [(dict(root_filters), root_total, 0)]

    while stack and nodes < max_nodes:
        filters, total, depth = stack.pop()
        nodes += 1
        if total <= threshold:
            leaves.append({"filters": filters, "total": total, "pages": math.ceil(total / size)})
            continue
        if depth >= min(max_depth, len(order)):
            # 已达切分深度上限仍超阈值 → oversized (需下一维度再切, 或接受窗口截断)
            window_pages = int(threshold // size) + (1 if threshold % size else 0)
            oversized.append(
                {"filters": filters, "total": total,
                 "pages_partial": window_pages, "lost": max(total - threshold, 0)}
            )
            continue
        dim = order[depth]
        api_calls += 1
        try:
            agg = client.fetch_aggregations(filters)
            values = agg.get(dim, {}).get("aggregations") or []
        except Exception as e:
            oversized.append({"filters": filters, "total": total, "lost": total, "reason": f"agg_err:{e}"})
            continue
        if not values:
            oversized.append({"filters": filters, "total": total, "lost": total, "reason": "无聚合值"})
            continue
        children = [(dict(filters) | {dim: v["origin_key"]}, int(v.get("value", 0))) for v in values]
        child_sum = sum(c for _, c in children)
        coverage = child_sum / total if total else 0
        if coverage < 0.9:
            mismatches.append(
                {"filters": filters, "total": total, "child_sum": child_sum, "coverage": round(coverage, 3), "dim": dim, "n": len(values)}
            )
        for cf, ct in reversed(children):
            stack.append((cf, ct, depth + 1))
        time.sleep(delay)

    return {
        "root_total": root_total,
        "leaves": leaves,
        "oversized": oversized,
        "mismatches": mismatches,
        "nodes": nodes,
        "api_calls": api_calls,
        "maxed_out": bool(stack),
    }


def print_plan(label: str, plan: Dict[str, Any], size: int, depth: int = 3) -> None:
    leaves = plan["leaves"]
    overs = plan["oversized"]
    sum_leaves = sum(l["total"] for l in leaves)
    over_total = sum(o["total"] for o in overs)
    over_lost = sum(o.get("lost", 0) for o in overs)
    plan_cov = (sum_leaves + over_total) / plan["root_total"] if plan["root_total"] else 0
    fetch_cov = (sum_leaves + sum(o["total"] - o.get("lost", 0) for o in overs)) / plan["root_total"] if plan["root_total"] else 0
    total_pages = sum(l["pages"] for l in leaves) + sum(o["pages_partial"] for o in overs if "pages_partial" in o)
    print(f"\n── 分桶预览: {label} (切分深度 {depth}) ──")
    print(f"  根 total              = {plan['root_total']:,}")
    print(f"  叶子桶数              = {len(leaves):,}")
    print(f"  超大桶数 (>threshold) = {len(overs):,}  合计 {over_total:,}")
    for o in overs[:8]:
        f = " & ".join(f"{k}={v}" for k, v in o["filters"].items() if v)
        print(f"      [超大] total={o['total']:,} 预计损失={o.get('lost',0):,} | {f}")
    print(f"  计划覆盖率 (含超大桶) = {plan_cov:.2%}")
    print(f"  可获取覆盖率 (窗口截断) = {fetch_cov:.2%}")
    print(f"  总翻页请求数          = {total_pages:,}  (size={size})")
    if plan["maxed_out"]:
        print(f"  ⚠ 达到 max_nodes 上限, 仍有未展开节点 (已检查 {plan['nodes']} 个节点)")
    print(f"  聚合接口调用数        = {plan['api_calls']:,} (仅切分节点触发)")
    eta_sec = total_pages / 5.0
    print(f"  预估爬取耗时          = {eta_sec/3600:.1f} 小时 (按 5 req/s 粗估)")


def run_plan_preview(client: PubscholarClient, threshold: int, size: int, max_nodes: int, delay: float, max_depth: int = 2) -> None:
    print("\n" + "=" * 70)
    print(f"【3】递归分治可行性预览 (threshold={threshold}, size={size}, max_nodes={max_nodes}, depth={max_depth})")
    print("=" * 70)
    for coll in CORE_COLLECTIONS:
        filters = _filters(coll)
        try:
            art = client.fetch_articles(filters, page=1, size=1)
            root_total = art.get("total", 0)
        except Exception as e:
            print(f"\n  {coll}: articles 请求失败 {e}")
            continue
        plan = build_plan(client, filters, root_total, PARTITION_ORDER, threshold, size, max_nodes, delay, max_depth)
        print_plan(coll, plan, size, max_depth)
        time.sleep(delay)


# ── main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="pubscholar v1 分桶爬取可行性验证")
    parser.add_argument("--window-only", action="store_true", help="只做窗口探测")
    parser.add_argument("--plan-only", action="store_true", help="只做分桶预览")
    parser.add_argument("--threshold", type=int, default=9900, help="叶子桶阈值 (默认 9900, 窗口上限10000留余量)")
    parser.add_argument("--size", type=int, default=50, help="每页条数 (默认 50)")
    parser.add_argument("--max-nodes", type=int, default=15000, help="分治最大节点数 (默认 15000)")
    parser.add_argument("--max-depth", type=int, default=3, help="切分深度上限 (默认 3: year→subject→source)")
    parser.add_argument("--delay", type=float, default=0.4, help="请求间隔秒数 (默认 0.4)")
    args = parser.parse_args()

    client = PubscholarClient()
    delay = args.delay

    if not args.plan_only:
        run_window_probe(client, delay)
        count_consistency(client, "基础 lang=C", _filters(), ["subject", "year", "type", "source"], delay)
        for coll in CORE_COLLECTIONS:
            count_consistency(client, coll, _filters(coll), ["subject", "year", "source"], delay)
        truncation_check(client, delay)

    if not args.window_only:
        run_plan_preview(client, args.threshold, args.size, args.max_nodes, delay, args.max_depth)

    print("\n验证完成。")


if __name__ == "__main__":
    main()
