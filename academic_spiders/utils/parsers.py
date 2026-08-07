"""
API 响应记录 → ArticleItem 字段解析器

统一 pubscholar_v1 / pubscholar_v2 / run_*_spider 的字段映射逻辑。
"""

from academic_spiders.items import ArticleItem


def record_to_item(record: dict, page: int, api_version: str = "v1") -> ArticleItem:
    """将 API 响应单条记录转为 ArticleItem

    :param record:  API 响应中的单条文献记录
    :param page:    当前页码（元信息，仅供 JSON 分组）
    :param api_version: "v1" 或 "v2"，影响个别字段的提取逻辑
    """

    if api_version == "v2":
        abstracts = (
            record.get("abstracts_cn")
            or record.get("abstracts")
            or record.get("abstracts_en")
            or ""
        )
        is_free = record.get("free", False) or record.get("is_free", False)
    else:
        abstracts = record.get("abstracts", "")
        is_free = record.get("is_free", False)

    date_str = record.get("date", "")
    year = int(date_str[:4]) if date_str and len(date_str) >= 4 else None

    return ArticleItem(
        _page=page,
        article_md5=record.get("id", ""),
        title=record.get("title", ""),
        abstracts=abstracts,
        key_words=record.get("keywords", []),
        author_names=record.get("author", []),
        source=record.get("source", ""),
        volume=record.get("volume", ""),
        issue=record.get("issue", ""),
        first_page=record.get("first_page", ""),
        last_page=record.get("last_page", ""),
        date=date_str,
        year=year,
        doi=record.get("doi", ""),
        cstr=record.get("cstr", ""),
        type=record.get("type", ""),
        article_type=record.get("article_type", ""),
        lang="zh",
        cn_type=record.get("cn_type", ""),
        is_free=is_free,
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
