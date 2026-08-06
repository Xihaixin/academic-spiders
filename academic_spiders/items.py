"""
Scrapy Item 定义 - 慧科研文献数据模型

字段映射关系:
  响应数据字段                 → Item 字段
  ─────────────────────────────────────────────
  id                          → article_md5
  title                       → title
  abstracts                   → abstracts
  keywords[]                  → key_words (JSON)
  author[]                    → author_names (JSON)
  authors[]                   → authors (原始JSON, 交给pipeline拆解)
  source                      → source
  volume / issue / first_page / last_page → ...
  date / year                 → date / year
  doi / cstr                  → doi / cstr
  type / article_type / cn_type / lang → ...
  is_free                     → is_free
  links[]                     → links (JSON)
  extendEntity                → extend_entity (JSON)
  semantic_entities           → semantic_entities (JSON)
  degree / major / school / tutor / graduation_institution → thesis_info
  source_list / license / local_links / attachments → extended_data
"""

import scrapy


class ArticleItem(scrapy.Item):
    """文献主记录 - 对应 articles 表"""

    # 元信息
    _page = scrapy.Field()              # 来源页码（内部使用）

    # 核心字段
    article_md5 = scrapy.Field()        # 平台文章ID (响应 id)
    title = scrapy.Field()              # 中文标题
    abstracts = scrapy.Field()          # 中文摘要
    key_words = scrapy.Field()          # 关键词 JSON 数组
    author_names = scrapy.Field()       # 作者姓名 JSON 数组
    source = scrapy.Field()             # 来源期刊
    volume = scrapy.Field()             # 卷
    issue = scrapy.Field()              # 期
    first_page = scrapy.Field()         # 起始页
    last_page = scrapy.Field()          # 结束页
    date = scrapy.Field()               # 出版日期
    year = scrapy.Field()               # 出版年份
    doi = scrapy.Field()                # DOI
    cstr = scrapy.Field()               # CSTR
    type = scrapy.Field()               # 文献类型
    article_type = scrapy.Field()       # 文献分类
    lang = scrapy.Field()               # 语种
    cn_type = scrapy.Field()            # 中文类型
    is_free = scrapy.Field()            # 是否免费
    links = scrapy.Field()              # 外部链接 JSON

    # 子表数据（原始JSON，pipeline 负责拆解写入）
    authors = scrapy.Field()            # 作者详细信息 (原始 JSON 数组)
    extend_entity = scrapy.Field()      # 扩展实体
    semantic_entities = scrapy.Field()  # 语义实体
    source_list = scrapy.Field()        # 来源列表
    license = scrapy.Field()            # 许可协议
    local_links = scrapy.Field()        # 本地链接
    attachments = scrapy.Field()        # 附件列表

    # 学位论文信息
    degree = scrapy.Field()
    major = scrapy.Field()
    school = scrapy.Field()
    tutor = scrapy.Field()
    graduation_institution = scrapy.Field()
