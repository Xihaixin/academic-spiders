"""
API 响应记录 → ArticleItem 字段解析器 (v3.2)

统一 pubscholar_v1 / pubscholar_v2 / run_*_spider 的字段映射逻辑。
"""

import hashlib
import re
from typing import Optional

from academic_spiders.items import ArticleItem


def build_dedup_key(doi: str, title: str, source: str, year) -> Optional[str]:
    """生成去重键 (二级降级)

    ① doi 非空 → "doi:"  + 规范化(小写) doi
    ② 否则     → "hash:" + md5(规范化title | source | year)
    ③ 都为空   → None (无法可靠去重)

    cstr 不参与去重 (值不可靠)。
    """
    if doi:
        return "doi:" + doi.strip().lower()

    if title and source:
        norm_title = re.sub(r"\s+", " ", title.strip())
        norm_source = source.strip()
        y = year if year is not None else ""
        raw = f"{norm_title}|{norm_source}|{y}"
        return "hash:" + hashlib.md5(raw.encode("utf-8")).hexdigest()

    return None


def record_to_item(record: dict, page: int, api_version: str = "v1") -> ArticleItem:
    """将 API 响应单条记录转为 ArticleItem

    :param record:       API 响应中的单条文献记录
    :param page:         当前页码 (元信息, 仅供 JSON 分组)
    :param api_version:  "v1" 或 "v2", 影响个别字段的提取逻辑
    """

    # ── v1 / v2 差异处理 ────────────────────────────────────
    if api_version == "v2":
        abstracts = (
            record.get("abstracts_cn")
            or record.get("abstracts")
            or record.get("abstracts_en")
            or ""
        )
    else:
        abstracts = record.get("abstracts", "")

    # ── extendEntity 提取 ──────────────────────────────────
    ext = record.get("extendEntity") or {}
    if isinstance(ext, str):
        import json
        try:
            ext = json.loads(ext)
        except json.JSONDecodeError:
            ext = {}

    cn_keywords = ext.get("cnKeywords") or []
    en_keywords = ext.get("enKeywords") or []
    contrib_institutions = ext.get("contrib_institution") or []

    # ── links 并入 local_link 属性 (平台 PDF 地址) ────────────
    # 在 links 第一个元素上挂载 local_link，而非追加新的链接元素
    links = list(record.get("links") or [])
    local_links = record.get("local_links") or []
    local_link_value = local_links[0] if local_links else ""

    if links:
        # 已有外部链接 → 在第一个元素上挂载 local_link 属性
        links[0]["local_link"] = local_link_value
    elif local_link_value:
        # 无外部链接但有平台 PDF → 单独挂载 (如部分学位论文)
        links.append({"local_link": local_link_value})

    # ── 日期与年份 ─────────────────────────────────────────
    date_str = record.get("date", "")
    raw_year = record.get("year")
    if raw_year is not None:
        year = int(raw_year) if isinstance(raw_year, str) else raw_year
    else:
        year = int(date_str[:4]) if date_str and len(date_str) >= 4 else None

    # ── authors 合并 author_id (按 sort_order 一一对应) ─────
    authors = record.get("authors") or []
    author_id_list = record.get("author_id") or []
    for i, author in enumerate(authors):
        if isinstance(author, dict) and i < len(author_id_list):
            author["author_id"] = author_id_list[i]

    # ── 核心字段提取 (供去重键生成) ─────────────────────────
    title = record.get("title", "")
    source = record.get("source", "")
    doi = record.get("doi", "")

    # ── 生成去重键 ─────────────────────────────────────────
    dedup_key = build_dedup_key(doi, title, source, year)

    return ArticleItem(
        _page=page,

        # 核心
        dedup_key=dedup_key,
        title=title,
        abstracts=abstracts,
        key_words=record.get("keywords", []),
        cn_keywords=cn_keywords,
        en_keywords=en_keywords,
        author_names=record.get("author", []),
        contrib_institutions=contrib_institutions,

        # 来源/期刊
        source=source,
        volume=record.get("volume", ""),
        issue=record.get("issue", ""),
        first_page=record.get("first_page", ""),
        last_page=record.get("last_page", ""),

        # 日期
        date=date_str,
        year=year,

        # 标识符
        doi=doi,
        cstr=record.get("cstr", ""),

        # 类型
        article_type=record.get("article_type", ""),
        lang="zh",

        # 链接 (合并后)
        links=links,

        # 作者详情 (pipeline 处理, 已合并 author_id)
        authors=authors,

        # 学位论文专属
        degree=record.get("degree", ""),
        major=record.get("major", ""),
        school=record.get("school", []),
        tutor=record.get("tutor", []),
        graduation_institution=record.get("graduation_institution", []),
    )
