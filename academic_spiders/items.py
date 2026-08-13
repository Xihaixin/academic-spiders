"""
Scrapy Item 定义 - 慧科研文献数据模型 (v3.1)

字段映射:
  响应字段                       → Item 字段
  ─────────────────────────────────────────────
  title                         → title
  abstracts                     → abstracts
  keywords[]                    → key_words (JSON)
  author[]                      → author_names (JSON)
  author_id[]                   → 合并到 authors[].author_id
  authors[]                     → authors (→ pipeline → article_authors)
  source                        → source
  volume / issue / first_page / last_page → ...
  date / year                   → date / year
  doi / cstr                    → doi / cstr
  article_type                  → article_type
  links[] + local_links[]       → links (JSON, 合并)
  extendEntity.cnKeywords       → cn_keywords (JSON)
  extendEntity.enKeywords       → en_keywords (JSON)
  extendEntity.contrib_institution → contrib_institutions (JSON)
  degree / major / school / tutor / graduation_institution → thesis_info
"""

import scrapy


class ArticleItem(scrapy.Item):
    """文献主记录 - 对应 articles 表 + article_thesis_info 表"""

    # 元信息
    _page = scrapy.Field()                  # 来源页码 (内部使用)

    # ── 核心字段 ────────────────────────────────────────────
    dedup_key = scrapy.Field()              # 去重键 (doi:/hash: 前缀)
    title = scrapy.Field()                  # 文献标题
    abstracts = scrapy.Field()              # 摘要 (与文献同语种)
    key_words = scrapy.Field()              # 关键词 JSON (来自 keywords)
    cn_keywords = scrapy.Field()            # 中文关键词 JSON (来自 extendEntity)
    en_keywords = scrapy.Field()            # 英文关键词 JSON (来自 extendEntity)
    author_names = scrapy.Field()           # 作者姓名 JSON (来自 author)
    contrib_institutions = scrapy.Field()   # 贡献机构 JSON (来自 extendEntity)

    # ── 来源/期刊信息 ─────────────────────────────────────
    source = scrapy.Field()                 # 来源名称
    volume = scrapy.Field()                 # 卷号
    issue = scrapy.Field()                  # 期号
    first_page = scrapy.Field()             # 起始页
    last_page = scrapy.Field()              # 结束页

    # ── 日期 ──────────────────────────────────────────────
    date = scrapy.Field()                   # 出版日期 (原始格式)
    year = scrapy.Field()                   # 出版年份

    # ── 文献标识符 ─────────────────────────────────────────
    doi = scrapy.Field()                    # DOI
    cstr = scrapy.Field()                   # CSTR

    # ── 类型 ──────────────────────────────────────────────
    article_type = scrapy.Field()           # 文献体裁 (期刊论文/学位论文/会议论文/预发布论文)
    lang = scrapy.Field()                   # 语种

    # ── 外部链接 (links + local_links 合并) ────────────────
    links = scrapy.Field()                  # 链接 JSON

    # ── 子表数据 (pipeline 负责拆解写入) ───────────────────
    authors = scrapy.Field()                # 作者详情 JSON (→ article_authors)

    # ── 学位论文专属 (→ article_thesis_info) ───────────────
    degree = scrapy.Field()
    major = scrapy.Field()
    school = scrapy.Field()
    tutor = scrapy.Field()
    graduation_institution = scrapy.Field()
