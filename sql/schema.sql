-- ============================================================
-- 公益学术平台(pubscholar.cn) 文献数据采集系统 - 数据库表结构
-- 版本: 3.2
-- 日期: 2026-08-13
-- 说明: 基于 v1 接口 (hky/open/resources/api/v1/articles) 真实响应数据设计
--       目标数据量: ~7400 万条中文文献记录
--       设计原则: 仅保留文献自身属性字段，剔除平台特有标记字段
-- ============================================================

-- 创建数据库（如不存在）
-- CREATE DATABASE IF NOT EXISTS academicdb DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE academicdb;


/*
 * ==== v3.1 → v3.2 主要变更 ====
 *
 *  新增字段 (articles):
 *    - dedup_key  VARCHAR(512)  UNIQUE  (去重键, 前缀区分类型: doi:/hash:)
 *
 *  新增表:
 *    - articles_audit_log  (去重审计表, 记录被覆盖的旧数据快照)
 *
 *  去重策略 (二级降级):
 *    ① doi  非空 → "doi:"  + 规范化小写 doi
 *    ② 否则      → "hash:" + md5(规范化title | source | year)
 *    ③ 都为空    → NULL (无法可靠去重, 直接插入)
 *    注意: cstr 不参与去重 (值不可靠)
 *
 *  v3.1 变更回顾:
 *    - 删除所有表的 article_md5 字段
 *
 * ==== 字段来源速查（响应数据路径 → 数据库表.字段）====
 *  响应.title                      → articles.title
 *  响应.abstracts                  → articles.abstracts
 *  响应.keywords[]                 → articles.key_words (JSON) + article_keywords (行)
 *  响应.author[]                   → articles.author_names (JSON)
 *  响应.authors[]                  → article_authors (每个元素一行)
 *  响应.author_id[]                → article_authors.author_id (按 sort_order 对应)
 *  响应.source                     → articles.source
 *  响应.{volume,issue,first_page,last_page} → articles.{...} (期刊论文专属)
 *  响应.{date,year}                → articles.{date,year}
 *  响应.{doi,cstr}                 → articles.{doi,cstr}
 *  响应.article_type               → articles.article_type
 *  响应.links[] + local_links[]    → articles.links (JSON, 合并)
 *  响应.extendEntity.cnKeywords    → articles.cn_keywords (JSON)
 *  响应.extendEntity.enKeywords    → articles.en_keywords (JSON)
 *  响应.extendEntity.contrib_institution → articles.contrib_institutions (JSON)
 *  响应.{degree,major,school,tutor,graduation_institution} → article_thesis_info
 */


-- ============================================================
-- 1. 文献主表 (articles)
--    存储文献核心书目信息，是所有文献类型的公共超集
--    预计数据量: ~7400万行
-- ============================================================
DROP TABLE IF EXISTS `articles_audit_log`;
DROP TABLE IF EXISTS `article_authors`;
DROP TABLE IF EXISTS `article_keywords`;
DROP TABLE IF EXISTS `article_thesis_info`;
DROP TABLE IF EXISTS `article_extended_data`;
DROP TABLE IF EXISTS `spider_run_log`;
DROP TABLE IF EXISTS `articles`;

CREATE TABLE `articles` (
    -- 自增主键
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',

    -- 去重键 (doi:/hash: 前缀, 用于跨批次去重)
    `dedup_key`             VARCHAR(512)    NULL COMMENT '去重键 (doi:/hash:)',

    -- 标题与摘要
    `title`                 TEXT            NULL COMMENT '文献标题',
    `abstracts`             LONGTEXT        NULL COMMENT '摘要 (与文献正文同语种)',

    -- 关键词
    `key_words`             JSON            NULL COMMENT '关键词列表 (来自响应 keywords)',
    `cn_keywords`           JSON            NULL COMMENT '中文关键词 (来自 extendEntity.cnKeywords)',
    `en_keywords`           JSON            NULL COMMENT '英文关键词 (来自 extendEntity.enKeywords)',

    -- 作者姓名简版 (JSON 数组)
    `author_names`          JSON            NULL COMMENT '作者姓名列表 (来自响应 author)',

    -- 贡献机构 (从 extendEntity.contrib_institution 提取)
    `contrib_institutions`  JSON            NULL COMMENT '贡献机构列表',

    -- 来源/期刊信息 (期刊论文专属, 其他类型为 NULL)
    `source`                VARCHAR(500)    NULL COMMENT '来源名称 (期刊名/预印本平台/大学名)',
    `volume`                VARCHAR(50)     NULL COMMENT '卷号',
    `issue`                 VARCHAR(50)     NULL COMMENT '期号',
    `first_page`            VARCHAR(50)     NULL COMMENT '起始页码',
    `last_page`             VARCHAR(50)     NULL COMMENT '结束页码',

    -- 日期 (格式不统一: "2026" / "2026-03-12" / "2026-5-6" / "202507")
    `date`                  VARCHAR(10)     NULL COMMENT '出版日期 (原始格式)',
    `year`                  INT             NULL COMMENT '出版年份 (从 date 提取, 用于分区)',

    -- 文献标识符
    `doi`                   VARCHAR(255)    NULL COMMENT 'DOI 标识符 (学位论文无)',
    `cstr`                  VARCHAR(200)    NULL COMMENT 'CSTR 标识符 (中国科技资源唯一标识)',

    -- 文献类型 (网站首页四种: 期刊论文, 学位论文, 会议论文, 预印本论文)
    `article_type`          VARCHAR(50)     NULL COMMENT '文献体裁 (期刊论文/学位论文/会议论文/预发布论文)',
    `lang`                  VARCHAR(50)     DEFAULT 'zh' COMMENT '文献语种 (zh/en/ja/...)',

    -- 外部链接 (合并 links + local_links)
    `links`                 JSON            NULL COMMENT '外部链接 [{"name":"期刊官网","url":"https://...","is_open_access":false}]',

    -- 审计字段
    `created_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    `updated_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',

    -- 约束与索引
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_dedup_key` (`dedup_key`),
    INDEX `idx_year` (`year`),
    INDEX `idx_source` (`source`(100)),
    INDEX `idx_doi` (`doi`(100)),
    INDEX `idx_article_type` (`article_type`),
    INDEX `idx_created_at` (`created_at`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献主表 - 存储文献核心书目信息 (所有类型公共超集)';


-- ============================================================
-- 2. 文献作者表 (article_authors)
--    从响应 authors[] 逐条提取，author_id 从响应 author_id[] 按 sort_order 对应
--    当前阶段不建立唯一作者主表，作者可能跨文献重复
--    预计数据量: ~5-10亿行 (每篇平均 5-10 位作者)
-- ============================================================
CREATE TABLE `article_authors` (
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`            BIGINT          NOT NULL COMMENT '关联 articles.id',

    `author_name`           VARCHAR(200)    NOT NULL COMMENT '作者姓名',
    `author_id`             VARCHAR(50)     NULL COMMENT '平台内作者ID (来自响应 author_id[], 按 sort_order 对应)',
    `is_corresponding`      TINYINT(1)      DEFAULT 0 COMMENT '是否通讯作者 0-否 1-是',
    `institutions`          JSON            NULL COMMENT '所属机构列表 ["武汉大学","南京大学"]',
    `sort_order`            SMALLINT        DEFAULT 0 COMMENT '作者排序 (从0开始)',

    PRIMARY KEY (`id`),
    INDEX `idx_article_id` (`article_id`),
    INDEX `idx_author_name` (`author_name`),
    INDEX `idx_author_id` (`author_id`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献作者表 - 记录每篇文献的作者、机构及平台内ID';


-- ============================================================
-- 3. 文献关键词表 (article_keywords)
--    来源: response.keywords + extendEntity.cnKeywords + extendEntity.enKeywords
--    按语种区分，支持统计分析热门研究主题
--    预计数据量: ~4-5亿行
-- ============================================================
CREATE TABLE `article_keywords` (
    `id`                    BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`            BIGINT          NOT NULL COMMENT '关联 articles.id',
    `keyword`               VARCHAR(500)    NOT NULL COMMENT '关键词',
    `lang`                  VARCHAR(10)     DEFAULT 'zh' COMMENT '语种 zh-中文 en-英文',
    `sort_order`            SMALLINT        DEFAULT 0 COMMENT '关键词排序',

    PRIMARY KEY (`id`),
    INDEX `idx_article_id` (`article_id`),
    INDEX `idx_keyword` (`keyword`(100)),
    INDEX `idx_lang` (`lang`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文献关键词表 - 规范化存储中英文关键词';


-- ============================================================
-- 4. 学位论文信息表 (article_thesis_info)
--    仅 article_type = "学位论文" 的记录写入 (~100万条)
--    与 articles 是 1:0..1 关系
-- ============================================================
CREATE TABLE `article_thesis_info` (
    `id`                        BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`                BIGINT          NOT NULL COMMENT '关联 articles.id',

    `degree`                    VARCHAR(200)    NULL COMMENT '学位类型 (博士/硕士/...)',
    `major`                     VARCHAR(500)    NULL COMMENT '专业方向',
    `school`                    JSON            NULL COMMENT '学校/培养单位列表',
    `tutor`                     JSON            NULL COMMENT '导师列表',
    `graduation_institution`    JSON            NULL COMMENT '毕业院校列表',

    `created_at`                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',

    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_article_id` (`article_id`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学位论文信息表 - 仅学位论文专属字段';


-- ============================================================
-- 5. 去重审计表 (articles_audit_log)
--    记录被去重覆盖的旧数据快照，用于验证去重策略的可靠性
--    仅在验证阶段使用，确认去重可靠后可清空或删除
-- ============================================================
CREATE TABLE `articles_audit_log` (
    `id`            BIGINT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `article_id`    BIGINT          NOT NULL COMMENT '被更新的 articles.id',
    `dedup_key`     VARCHAR(512)    NULL COMMENT '触发冲突的去重键',
    `old_data`      JSON            NULL COMMENT '被覆盖前的旧记录快照',
    `new_data`      JSON            NULL COMMENT '新记录快照 (用于对比)',
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '冲突发生时间',

    PRIMARY KEY (`id`),
    INDEX `idx_article_id` (`article_id`),
    INDEX `idx_dedup_key` (`dedup_key`(100)),
    INDEX `idx_created_at` (`created_at`)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='去重审计表 - 记录被去重覆盖的旧数据快照，用于验证去重可靠性';


-- ============================================================
-- 6. 爬虫运行日志表 (spider_run_log)
--    记录每次爬虫运行的统计信息
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
-- ## 表关系
--
--   articles (1) ──── (N) article_authors
--        │
--        ├── (1) ──── (0..1) article_thesis_info   (仅 article_type="学位论文")
--        └── (1) ──── (N) article_keywords
--
--   spider_run_log        (独立日志)
--   articles_audit_log    (去重审计, 验证阶段)
--
--
-- ## articles 字段分类
--
--   所有文献类型共有:  id, dedup_key, title, abstracts,
--                     key_words, cn_keywords, en_keywords,
--                     author_names, contrib_institutions,
--                     source, date, year, cstr,
--                     article_type, lang, links
--
--   期刊/会议论文专属:  volume, issue, first_page, last_page, doi
--   预印本可能有:       doi (部分有)
--   学位论文专属:       (见 article_thesis_info)
--
--
-- ## 关于 article_md5 为何删除
--
--   响应中的 "id" 字段是一个 32 位 MD5 哈希，本质上是平台内部的记录标识。
--   该值后续如果需要（如构造 PDF 下载链接），可以从 links/local_links 中的
--   PDF 文件名（文件名本身即为 MD5）推导，无需在数据库中冗余存储。
--
--
-- ## 关于去重策略 (二级降级)
--
--   dedup_key 生成优先级:
--     ① doi 非空        → "doi:"  + 规范化(小写) doi
--     ② 否则            → "hash:" + md5(规范化title | source | year)
--     ③ title/source 均空 → NULL (无法可靠去重, 直接插入)
--
--   cstr 不参与去重 (值不可靠)。
--
--   articles_audit_log 记录被覆盖的旧数据，用于验证阶段排查:
--     - 去重是否真的命中了重复记录
--     - 命中的两条记录是否真的是同一篇文献 (去重键可靠性)
--
--
-- ## 数据写入流程 (Pipeline 处理单条文献)
--
--   1. 若 dedup_key 非空: SELECT id FROM articles WHERE dedup_key = ?
--      已存在 → 将旧记录快照写入 articles_audit_log，再 UPDATE articles
--      不存在 → INSERT articles (ON DUPLICATE KEY UPDATE 兜底处理竞态)
--   2. 若 dedup_key 为空: 直接 INSERT articles
--   3. DELETE + INSERT article_authors (含 author_id)
--   4. DELETE + INSERT article_keywords (zh + en 分开)
--   5. IF article_type = "学位论文":
--        INSERT INTO article_thesis_info ... ON DUPLICATE KEY UPDATE ...
--
--
-- ## 分区建议（生产环境）
--
--   articles 表 ~7400万行，建议按 year RANGE 分区:
--
--   ALTER TABLE articles PARTITION BY RANGE (year) (
--       PARTITION p_before_2020 VALUES LESS THAN (2020),
--       PARTITION p_2020 VALUES LESS THAN (2021),
--       ...
--       PARTITION p_2026 VALUES LESS THAN (2027),
--       PARTITION p_future VALUES LESS THAN MAXVALUE
--   );
--
--   注意: 分区键必须包含在 PRIMARY KEY 中，启用分区时改为 PRIMARY KEY (id, year)
--
--
-- ## 存储估算
--
--   articles:             ~7400万行 × ~1.5KB/行 ≈ 110GB
--   article_authors:      ~6亿行   × ~250B/行  ≈ 150GB
--   article_keywords:     ~5亿行   × ~180B/行  ≈  90GB
--   article_thesis_info:  ~100万行 × ~200B/行  ≈  <1GB
--   articles_audit_log:   验证阶段少量
--   总计预估: ~351GB (建议预留 500GB+)
-- ============================================================
