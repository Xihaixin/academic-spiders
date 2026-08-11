-- ============================================================
-- 慧科研 (pubscholar.cn) 文献数据采集系统 - 数据库表结构
-- 版本: 2.0
-- 日期: 2026-08-06
-- 说明: 基于 v1 接口 (hky/open/resources/api/v1/articles) 响应数据设计
--       目标数据量: ~7400 万条中文文献记录
--       修订: 精简 articles 主表，拆分扩展数据到独立表
-- ============================================================

-- 创建数据库（如不存在）
-- CREATE DATABASE IF NOT EXISTS academicdb DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE academicdb;


/*
 * ==== 修订说明 ====
 * v1.0 → v2.0 主要变更:
 *  1. articles 表新增 BIGINT 自增主键，原响应 "id" → article_md5 唯一索引
 *  2. articles 表精简：仅保留核心书目字段（标题/摘要/期刊/卷期/DOI/类型/年份）
 *  3. extend_entity / semantic_entities / source_list / license 等 → article_extended_data 表
 *  4. degree / major / school / tutor / graduation_institution → article_thesis_info 表
 *  5. 新增 key_words JSON 字段在 articles 表中（同时保留 article_keywords 用于规范化查询）
 *  6. 所有子表统一使用 article_id(BIGINT) + article_md5(VARCHAR) 双关联字段
 *  7. 删除 author_inner_id、browse_count、abstracts_abbr、author_ids 等不需要的字段
 *
 * ==== 字段来源速查（响应数据路径 → 数据库表.字段）====
 *  响应.id                    → articles.article_md5
 *  响应.title                 → articles.title
 *  响应.abstracts             → articles.abstracts
 *  响应.keywords[]            → articles.key_words (JSON) + article_keywords (行)
 *  响应.author[]              → articles.author_names (JSON)
 *  响应.authors[]             → article_authors (每个元素一行)
 *  响应.source                → articles.source
 *  响应.{volume,issue,first_page,last_page} → articles.{volume,issue,first_page,last_page}
 *  响应.{date,year}           → articles.{date,year}
 *  响应.{doi,cstr}            → articles.{doi,cstr}
 *  响应.{type,article_type,cn_type,lang} → articles.{type,article_type,cn_type,lang}
 *  响应.is_free               → articles.is_free
 *  响应.extendEntity          → article_extended_data.extend_entity
 *  响应.semantic_entities     → article_extended_data.semantic_entities
 *  响应.{source_list,license,local_links,attachments} → article_extended_data
 *  响应.{degree,major,school,tutor,graduation_institution} → article_thesis_info
 *  响应.links[]               → articles.links (JSON)
 */


/*
  1. 确定数据表：article 主表
  2. 文献-作者关联表：article_authors

  - spider 运行状态表

  对表进行调整的前置思考：
  1. article 表里面已经存在 author_names, key_words(只有中文),
  2. is_free 字段是否可以使用 is_open_access 
  3. 关于 links 字段，它里面只有 url 和 is_open_access 是有用字段
  4. links.url 与 doi 两个字段之间的联系：links.url 等于 doi 前面加上一个 https://doi.org 吗
  5. type, article_type 它们都用来表示当前论文的类型，那么三者之间有什么区别呢 ？
     我看到首页显示了四种论文类型：期刊论文, 学位论文, 会议论文, 预印本论文
  - date 和 year 两个字段确实不太一样：比如在查看 “学位论文”时，date: 202507, year: 2025
  - 如果是学位论文的话，它的字段结构还是有一点不太一样：它有对应的 degree, tutor 导师, 没有所谓的 doi, volume, issue 有一个graduation_institution 这个应该是毕业的机构


  6. cstr 在中国科学院、国家科技基础条件平台中心等机构建设的系统中，cstr 是给科技资源（包括论文、数据集、仪器设备等）分配的唯一永久标识符，类似于国际通用的 DOI（数字对象标识符）。
  7. 在 article 表中还有一个比较关键的 url link，似乎是 local_link 似乎是平台服务器上所保存的文件地址，这个字段是否也应该添加上，如果有的话？
  8. 论文的封面是什么样的 ？

  建立一个新表 article_info 另外还有一个问题：在平台首页展示出来的论文简略信息列表元素中，那些卡片实际上应该是一个点击后可以跳转的链接，我们应该存储这些 url ，因为我们需要跳转到论文详情页中获取更丰富的数据
  - 表 article_extended_data 是否有必要存在 ？可这里卖弄的额字段似乎只有三个关键内容：中文关键词，英文关键词，contrib_institution 机构名称

  contrib_institution 机构与 institution 以及 graduation_institution 这三个字段之间的区别是什么 ？
  - 学位论文有 graduation_institution
  - 


  我看到响应内容中既有中文摘要，也有英文摘要，实际上没有必要将两个摘要都放在 article 表中；我们在 article 表中只存放与论文一致语言的关键词列表。这么一看，article_keyword 表确实有存在的必要
  关于 article_thesis_info 表用于存储学位论文，具体中文文献中大约有 100 万左右的数据。具体有什么作用？
  如何判断所获取的文献是否属于学位论文这种类型？ article_type : "学位论文"，在响应体中是根据 article_type 进行判断 
  它里面的字段对应的数据是从哪里获取的 ？为什么为全部都是空值 ？ 是我的程序解析问题，还是压根就不存在那些字段 ？

*/

-- ============================================================
-- 1. 文献主表 (articles)
--    仅存储文献的核心书目信息，保持表结构精简
--    预计数据量: ~7400万行
-- ============================================================
DROP TABLE IF EXISTS `article_authors`;
DROP TABLE IF EXISTS `article_keywords`;
DROP TABLE IF EXISTS `article_thesis_info`;
DROP TABLE IF EXISTS `article_extended_data`;
DROP TABLE IF EXISTS `articles`;

CREATE TABLE `articles` (
    -- 自增主键 (InnoDB 聚簇索引，BIGINT 顺序写入性能最优)
    `id`                BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',

    -- 平台原始文章 ID (来自响应数据中的 "id" 字段，32位MD5)
    `article_md5`       VARCHAR(32)     NOT NULL COMMENT '平台文章标识 (响应数据id字段)',

    -- 标题与摘要
    `title`             TEXT            NULL COMMENT '中文标题',
    `abstracts`         LONGTEXT        NULL COMMENT '中文摘要（完整版）',

    -- 关键词 (原始 JSON 数组，规范化查询见 article_keywords 表)
    `key_words`         JSON            NULL COMMENT '关键词列表 ["水稻","株型","叶夹角"]',

    -- 作者姓名简版 (JSON 数组，完整信息见 article_authors 表)
    `author_names`      JSON            NULL COMMENT '作者姓名列表 ["鲜凤君","刘淑雅"]',

    -- 来源/期刊信息
    `source`            VARCHAR(500)    NULL COMMENT '来源期刊/会议名称',
    `volume`            VARCHAR(50)     NULL COMMENT '卷号',
    `issue`             VARCHAR(50)     NULL COMMENT '期号',
    `first_page`        VARCHAR(50)     NULL COMMENT '起始页码',
    `last_page`         VARCHAR(50)     NULL COMMENT '结束页码',

    -- 日期
    `date`              VARCHAR(10)     NULL COMMENT '出版日期 (如 "2026", "2026-03-12")',
    `year`              INT             NULL COMMENT '出版年份（用于分区）',

    -- 文献标识符
    `doi`               VARCHAR(255)    NULL COMMENT 'DOI 标识符',
    `cstr`              VARCHAR(200)    NULL COMMENT 'CSTR 标识符',

    -- 文献类型
    `type`              VARCHAR(50)     NULL COMMENT '文献类型 (article/review/...)',
    `article_type`      VARCHAR(50)     NULL COMMENT '文献分类',
    `lang`              VARCHAR(50)     DEFAULT 'zh' COMMENT '文献语种 (zh/en/...)',
    `cn_type`           VARCHAR(50)     NULL COMMENT '中文类型 (论文/学位论文/专利/...)',

    -- 访问权限
    `is_free`           TINYINT(1)      DEFAULT 0 COMMENT '是否免费获取 0-否 1-是',

    -- 外部链接 (JSON 数组，从响应 links 提取，含 link_name / url / is_open_access)
    `links`             JSON            NULL COMMENT '外部链接 [{"name":"期刊官网","url":"https://...","is_open_access":false}]',

    -- 审计字段
    `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    `updated_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',

    -- 约束与索引
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_article_md5` (`article_md5`),
    INDEX `idx_year` (`year`),
    INDEX `idx_source` (`source`(100)),
    INDEX `idx_doi` (`doi`(100)),
    INDEX `idx_type` (`type`),
    INDEX `idx_cn_type` (`cn_type`),
    INDEX `idx_lang` (`lang`),
    INDEX `idx_date` (`date`),
    INDEX `idx_created_at` (`created_at`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献主表 - 仅存储核心书目信息，扩展数据见关联表';


-- ============================================================
-- 2. 文献扩展数据表 (article_extended_data)
--    存储 extendEntity 和 semantic_entities 等非核心元数据
--    与 articles 是 1:1 关系
--    预计数据量: ~7400万行
-- ============================================================
CREATE TABLE `article_extended_data` (
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`            BIGINT          NOT NULL COMMENT '关联 articles.id',
    `article_md5`           VARCHAR(32)     NOT NULL COMMENT '关联 articles.article_md5 (冗余)',

    -- 扩展实体 (响应数据中的 extendEntity 完整 JSON)
    -- 包含: cnKeywords, enKeywords, contrib_institution, fulltext_permission,
    --       datasource-link, project_name, base_project, is_cas_representative,
    --       is_high_level, article_legal_status, wos-category-llm, base_subject,
    --       article-id, article-id-type, title-repeated, journal-repeated 等
    `extend_entity`         JSON            NULL COMMENT '扩展实体完整元数据',

    -- 语义实体标注
    `semantic_entities`     JSON            NULL COMMENT '语义实体标注',

    -- 其他辅助信息
    `source_list`           JSON            NULL COMMENT '数据来源标识列表',
    `license`               VARCHAR(200)    NULL COMMENT '许可协议',
    `local_links`           JSON            NULL COMMENT '本地预览链接列表',
    `attachments`           JSON            NULL COMMENT '附件列表',

    `created_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',

    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_article_id` (`article_id`),
    INDEX `idx_article_md5` (`article_md5`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献扩展数据表 - 1:1 存储 extendEntity/semanticEntities 等完整元数据';


-- ============================================================
-- 3. 学位论文信息表 (article_thesis_info)
--    仅对 cn_type = "学位论文" 的记录写入，其他类型无数据
--    与 articles 是 1:0..1 关系
--    预计数据量: 远小于 articles 主表
-- ============================================================
CREATE TABLE `article_thesis_info` (
    `id`                        BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`                BIGINT          NOT NULL COMMENT '关联 articles.id',
    `article_md5`               VARCHAR(32)     NOT NULL COMMENT '关联 articles.article_md5 (冗余)',

    `degree`                    VARCHAR(200)    NULL COMMENT '学位类型 (博士/硕士/...)',
    `major`                     VARCHAR(500)    NULL COMMENT '专业方向',
    `school`                    JSON            NULL COMMENT '学校/培养单位列表',
    `tutor`                     JSON            NULL COMMENT '导师列表',
    `graduation_institution`    JSON            NULL COMMENT '毕业院校列表',

    `created_at`                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',

    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_article_id` (`article_id`),
    INDEX `idx_article_md5` (`article_md5`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学位论文信息表 - 仅存储学位论文专属字段，非学位论文无此行';


-- ============================================================
-- 4. 文献作者表 (article_authors)
--    从响应数据 authors 数组中逐条提取，规范化存储
--    注意: 当前不建立唯一作者主表，作者可能跨文献重复。
--          未来可通过数据清洗构建独立的 authors 主表。
--    预计数据量: ~5-10亿行 (每篇文章平均 5-10 位作者)
-- ============================================================
CREATE TABLE `article_authors` (
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`            BIGINT          NOT NULL COMMENT '关联 articles.id',
    `article_md5`           VARCHAR(32)     NOT NULL COMMENT '关联 articles.article_md5 (冗余)',
    `author_name`           VARCHAR(200)    NOT NULL COMMENT '作者姓名',
    `is_corresponding`      TINYINT(1)      DEFAULT 0 COMMENT '是否通讯作者 0-否 1-是',
    `institutions`          JSON            NULL COMMENT '所属机构列表 ["武汉大学","南京大学"]',
    `sort_order`            SMALLINT        DEFAULT 0 COMMENT '作者排序（从0开始）',

    PRIMARY KEY (`id`),
    INDEX `idx_article_id` (`article_id`),
    INDEX `idx_article_md5` (`article_md5`),
    INDEX `idx_author_name` (`author_name`),
    INDEX `idx_is_corresponding` (`is_corresponding`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献作者表 - 记录每篇文献的作者及其机构信息';


-- ============================================================
-- 5. 文献关键词表 (article_keywords)
--    从 keywords 数组和 extendEntity.cnKeywords/enKeywords 中提取
--    支持按语种区分，便于统计分析热门研究主题
--    预计数据量: ~4-5亿行
-- ============================================================
CREATE TABLE `article_keywords` (
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`            BIGINT          NOT NULL COMMENT '关联 articles.id',
    `article_md5`           VARCHAR(32)     NOT NULL COMMENT '关联 articles.article_md5 (冗余)',
    `keyword`               VARCHAR(500)    NOT NULL COMMENT '关键词',
    `lang`                  VARCHAR(10)     DEFAULT 'zh' COMMENT '语种 zh-中文 en-英文',
    `sort_order`            SMALLINT        DEFAULT 0 COMMENT '关键词排序',

    PRIMARY KEY (`id`),
    INDEX `idx_article_id` (`article_id`),
    INDEX `idx_article_md5` (`article_md5`),
    INDEX `idx_keyword` (`keyword`(100)),
    INDEX `idx_lang` (`lang`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献关键词表 - 规范化存储中英文关键词';


-- ============================================================
-- 6. 爬虫运行日志表 (spider_run_log)
--    记录每次爬虫运行的统计信息，便于监控与审计
-- ============================================================
CREATE TABLE `spider_run_log` (
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT,
    `run_id`                VARCHAR(36)     NOT NULL COMMENT '运行批次UUID',
    `spider_name`           VARCHAR(100)    NOT NULL COMMENT '爬虫名称',
    `start_time`            DATETIME        NULL COMMENT '开始时间',
    `end_time`              DATETIME        NULL COMMENT '结束时间',
    `status`                VARCHAR(20)     DEFAULT 'running' COMMENT '运行状态: running/completed/failed',
    `total_requests`        BIGINT          DEFAULT 0 COMMENT '总请求数',
    `total_items`           BIGINT          DEFAULT 0 COMMENT '成功入库数',
    `total_errors`          BIGINT          DEFAULT 0 COMMENT '错误数',
    `last_page`             INT             DEFAULT 0 COMMENT '最后爬取页码',
    `error_message`         TEXT            NULL COMMENT '错误信息',
    `extra_info`            JSON            NULL COMMENT '额外信息 (请求参数等)',

    PRIMARY KEY (`id`),
    INDEX `idx_run_id` (`run_id`),
    INDEX `idx_start_time` (`start_time`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='爬虫运行日志表';


-- ============================================================
-- 设计说明
-- ============================================================
--
-- ## 表关系总览
--
--   articles (1) ────── (1) article_extended_data   扩展元数据 (extendEntity 等)
--        │
--        ├── (1) ────── (0..1) article_thesis_info  学位论文专属信息
--        │                                           (非学位论文无对应行)
--        ├── (1) ────── (N) article_authors          作者列表
--        └── (1) ────── (N) article_keywords         关键词列表
--
--
-- ## 字段分布逻辑
--
--   ┌─────────────────────┬──────────────────────────────────────┐
--   │ 表                  │ 存储内容                              │
--   ├─────────────────────┼──────────────────────────────────────┤
--   │ articles            │ 核心书目信息: 标题/摘要/期刊/卷期页码 │
--   │ (核心表)            │ /DOI/类型/年份/关键词(JSON)/作者(JSON)│
--   │                     │ /links(JSON) 外部链接                 │
--   │                     │ 每条文献必须且高频访问的字段           │
--   ├─────────────────────┼──────────────────────────────────────┤
--   │ article_extended_   │ extendEntity 完整 JSON (40+ 子字段)   │
--   │ data                │ semantic_entities / source_list /     │
--   │                     │ license / local_links / attachments   │
--   │                     │ 低频访问的辅助元数据                   │
--   ├─────────────────────┼──────────────────────────────────────┤
--   │ article_thesis_info │ degree / major / school / tutor /    │
--   │                     │ graduation_institution                │
--   │                     │ 仅 cn_type = "学位论文" 才有数据      │
--   └─────────────────────┴──────────────────────────────────────┘
--
--
-- ## 关于 BIGINT 自增主键 (articles.id)
--
--   InnoDB 使用聚簇索引，主键值存储在每个二级索引的叶子节点中:
--   - BIGINT(8字节) vs VARCHAR(32)(32字节): 每个二级索引条目节省 24 字节
--   - 顺序 INSERT (自增) vs 随机 INSERT (MD5): 减少页分裂，提升写入性能
--   - 整数 JOIN vs 字符串 JOIN: 比较效率更高
--   - article_md5 作为 UNIQUE KEY 保持平台 ID 的唯一约束和数据可追溯性
--
--
-- ## 关于子表中的 article_md5 冗余列
--
--   子表同时存储 article_id (BIGINT FK) 和 article_md5 (VARCHAR(32)):
--   - article_id: 用于 JOIN articles 表 (整数比较快)
--   - article_md5: 用于:
--       1) Pipeline 中直接通过响应 "id" 值查询关联，无需先 JOIN articles
--       2) 数据导出/迁移时保持与源数据的直接可追溯性
--   存储成本: ~40 字节/行，对于 10 亿行约 40GB，在总体 500GB+ 预算中可接受
--
--
-- ## 关于作者表设计（当前阶段）
--
--   article_authors 是 "文献-作者" 关联表，不建立唯一作者主表。
--   这意味着同一作者在不同文献中出现时会有多条记录。
--   这是有意为之的设计:
--   - 第一阶段: 原始数据直接入库，不进行作者实体识别
--   - 第二阶段: 数据完备后，通过 GROUP BY author_name + institutions
--     清洗去重构建独立的 authors 主表 + author_article_map 关联表
--
--
-- ## 数据写入流程 (Pipeline 处理单条文献)
--
--   1. INSERT INTO articles (...) VALUES (...)
--      ON DUPLICATE KEY UPDATE title=VALUES(title), ...
--   2. 获取 articles.id:
--      SET @aid = LAST_INSERT_ID();  -- 新插入时有效
--      -- 或 SELECT id INTO @aid FROM articles WHERE article_md5 = ?;
--   3. 写入子表 (先删后插，保证数据一致性):
--      DELETE FROM article_authors WHERE article_id = @aid;
--      INSERT INTO article_authors (...) VALUES (...), (...), ...;
--      (article_keywords 同理)
--   4. INSERT INTO article_extended_data (...) VALUES (...)
--      ON DUPLICATE KEY UPDATE extend_entity=VALUES(extend_entity), ...
--   5. IF cn_type = '学位论文':
--        INSERT INTO article_thesis_info (...) VALUES (...)
--        ON DUPLICATE KEY UPDATE degree=VALUES(degree), ...
--
--
-- ## 分区建议（生产环境）
--
--   articles 表 ~7400万行，强烈建议按 year 字段 RANGE 分区:
--
--   ALTER TABLE articles PARTITION BY RANGE (year) (
--       PARTITION p_before_2020 VALUES LESS THAN (2020),
--       PARTITION p_2020 VALUES LESS THAN (2021),
--       PARTITION p_2021 VALUES LESS THAN (2022),
--       PARTITION p_2022 VALUES LESS THAN (2023),
--       PARTITION p_2023 VALUES LESS THAN (2024),
--       PARTITION p_2024 VALUES LESS THAN (2025),
--       PARTITION p_2025 VALUES LESS THAN (2026),
--       PARTITION p_2026 VALUES LESS THAN (2027),
--       PARTITION p_future VALUES LESS THAN MAXVALUE
--   );
--
--   注意: MySQL 分区键必须包含在所有 UNIQUE KEY 中。
--   如启用分区，需将:
--     PRIMARY KEY 改为 (id, year)
--     UNIQUE KEY uk_article_md5 改为 (article_md5, year)
--
--
-- ## 存储估算
--
--   articles:              ~7400万行 × ~1.2KB/行 ≈  90GB
--   article_extended_data: ~7400万行 × ~800B/行  ≈  60GB
--   article_thesis_info:   少量 (< 1000万)            < 5GB
--   article_authors:       ~6亿行   × ~250B/行   ≈ 150GB
--   article_keywords:      ~5亿行   × ~180B/行   ≈  90GB
--   总计预估: ~395GB (建议预留 550GB+)
-- ============================================================
