# 慧科研 (pubscholar.cn) 文献数据采集系统 - 数据库表结构 V3 设计方案

**日期**: 2026-08-12
**版本**: 3.0（待审核）

---

## 一、版本演进

| 版本 | 主要变化 |
|------|----------|
| v1.0 | 初始方案，articles 32 字段，VARCHAR PK |
| v2.0 | BIGINT 自增PK，扩展开独立表(extended_data + thesis_info)，精简 articles |
| **v3.0** | **删减无价值字段/表，提取 extendEntity 中有用字段，合并 thesis_info，新加 author_id** |

---

## 二、V2 → V3 变更总览

### 2.1 表结构变化

| 操作 | 表名 | 原因 |
|------|------|------|
| **删除** | `article_extended_data` | 6 个字段中 4 个无价值(semantic_entities/license/source_list/attachments 全部为空)，仅剩 2 个有用字段(contrib_institution, classification_bg)提取到 articles 表 |
| **删除** | `article_thesis_info` | 仅 ~100万条学位论文，增删字段不频繁，合并回 articles 避免 JOIN 和维护成本 |

最终保留 **4 张表**:
- `articles` — 文献主表
- `article_authors` — 作者关联表
- `article_keywords` — 关键词表
- `spider_run_log` — 爬虫运行日志

### 2.2 articles 表字段变化

#### 删除的字段 (8个)：

| 字段 | 删除原因 |
|------|----------|
| `type` | 响应数据中 **始终为 "article"**，无区分度 |
| `cn_type` | 响应数据中 **始终为 "论文"**，无区分度。真正的类型由 `article_type` 表示 |
| `lang` | **响应数据中不存在该字段**（它只出现在请求参数 `aggregations.lang` 中，用于请求过滤） |
| `is_free` | **平台特有字段**，反映的是 pubscholar 自身的开放获取状态，不是论文本身的 OA 属性 |
| `semantic_entities` | 所有采样数据中 **恒为空对象 `{}`** |
| `license` | 所有采样数据中 **恒为空字符串** |
| `source_list` | 平台数据处理流水线标识（如 `"neweditarticle"`, `"pubscholar_running"`），非论文元数据 |
| `attachments` | 所有采样数据中 **恒为空数组 `[]`** |
| `local_links` | **合并入 `links` JSON**，与外部链接统一管理 |
| `abstracts_abbreviation` | 可从 `abstracts` 截取生成，**爬虫阶段不写入此字段** |

#### 新增的字段 (7个)：

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `contrib_institutions` | JSON | extendEntity.contrib_institution | 机构级贡献者（与作者级 institutions 不同）。如 `[["武汉大学"],["南京大学"]]` |
| `subject_classification` | JSON | extendEntity.classification_bg | 学科分类。如 `["应用心理学","电脑、计算机"]` |
| `degree` | VARCHAR(200) | root.degree | 学位类型（博士/硕士），原 thesis_info 表 |
| `major` | VARCHAR(500) | root.major | 专业方向 |
| `school` | JSON | root.school | 学校/培养单位列表 |
| `tutor` | JSON | root.tutor | 导师列表 |
| `graduation_institution` | JSON | root.graduation_institution | 毕业院校列表 |

#### 保留的字段 (18个)：

`id`, `article_md5`, `title`, `abstracts`, `key_words`, `author_names`, `source`, `volume`, `issue`, `first_page`, `last_page`, `date`, `year`, `doi`, `cstr`, `article_type`, `links`, `created_at`, `updated_at`

> **注意**: `article_md5` 改为 `NULL` 可空 — 用户指出并非所有记录都存在该字段。

### 2.3 article_authors 表变化

| 操作 | 字段 | 说明 |
|------|------|------|
| **新增** | `author_id` VARCHAR(32) NULL | 平台内部作者 ID（响应 `author_id[]` 数组，与 `author[]` 并行），可用于未来作者去重。并非所有类型都有此字段（预印本/预发布论文通常为空） |

### 2.4 article_keywords 表
**无变化**。继续从 `keywords`(根) + `extendEntity.cnKeywords` + `extendEntity.enKeywords` 三条数据源提取并规范存储。

---

## 三、最终表结构

### 3.1 articles（文献主表）

```
articles
├── id                    BIGINT PK AUTO_INCREMENT    自增主键
├── article_md5           VARCHAR(32) NULL           平台文章标识（可能为空）
├── title                 TEXT                        标题
├── abstracts             LONGTEXT                    摘要
├── key_words             JSON                        关键词（论文同语种）
├── author_names          JSON                        作者姓名列表
├── source                VARCHAR(500)                来源期刊/会议
├── volume / issue / first_page / last_page           卷期页码
├── date                  VARCHAR(20)                 出版日期（格式不统一）
├── year                  INT                         出版年份（用于分区）
├── doi                   VARCHAR(255)                DOI
├── cstr                  VARCHAR(200)                CSTR 科技资源标识
├── article_type          VARCHAR(50)                 文献类型（期刊论文/学位论文/会议论文/预印本论文）
├── links                 JSON                        链接 [{"name":"","url":"","is_open_access":false}, ...]
│                                                     （含 local_links 平台 PDF 预览链接）
├── contrib_institutions  JSON                        贡献机构（来自 extendEntity）
├── subject_classification JSON                      学科分类（来自 extendEntity）
├── degree                VARCHAR(200)                学位类型（仅学位论文）
├── major                 VARCHAR(500)                专业方向（仅学位论文）
├── school                JSON                        学校列表（仅学位论文）
├── tutor                 JSON                        导师列表（仅学位论文）
├── graduation_institution JSON                      毕业院校（仅学位论文）
├── created_at / updated_at DATETIME                  审计字段
└── INDEXES: uk_article_md5, idx_year, idx_source, idx_doi, idx_article_type, idx_date
```

### 3.2 article_authors（文献-作者关联表）

```
article_authors
├── id                    BIGINT PK AUTO_INCREMENT
├── article_id            BIGINT NOT NULL              → articles.id
├── article_md5           VARCHAR(32) NOT NULL        冗余关联
├── author_id             VARCHAR(32) NULL            平台内部作者ID（新增）
├── author_name           VARCHAR(200) NOT NULL       作者姓名
├── is_corresponding      TINYINT(1) DEFAULT 0        是否通讯作者
├── institutions          JSON                        所属机构列表
├── sort_order            SMALLINT DEFAULT 0          排序
└── INDEXES: idx_article_id, idx_article_md5, idx_author_name, idx_is_corresponding
```

### 3.3 article_keywords（关键词表，不变）

```
article_keywords
├── id / article_id / article_md5
├── keyword               VARCHAR(500)
├── lang                  VARCHAR(10)    zh / en
├── sort_order            SMALLINT
└── INDEXES: idx_article_id, idx_article_md5, idx_keyword, idx_lang
```

### 3.4 spider_run_log（爬虫运行日志表，不变）

---

## 四、关键设计决策说明

### 4.1 为什么删除 article_extended_data 和 article_thesis_info

- **article_extended_data**: 6 个字段中仅有 `extend_entity` 中的 `contrib_institution` 和 `classification_bg` 有价值，提取到 articles 后该表无剩余用途。其余字段（semantic_entities, license, source_list, attachments）在所有采样数据中恒为空。
- **article_thesis_info**: 虽然学位论文约 100 万条，但作为 1:1 表带来的维护成本（需要额外 JOIN、需要判断类型再写入）高于收益。将 5 个字段合并到 articles 对非学位论文行为 NULL，MySQL 对 NULL 列存储开销极小。

### 4.2 为什么移除 type / cn_type / lang

通过分析所有示例响应数据：
- `type` = 始终 `"article"`，即使是学位论文和预印本也标记为此值
- `cn_type` = 始终 `"论文"`，不因类型变化
- `lang` = 响应数据中**不存在此字段**（它仅在**请求参数**中出现，用于过滤语种，如 `"lang":"C"` 表示中文）

真正的类型区分由 `article_type` 承担：`"期刊论文"` | `"学位论文"` | `"会议论文"` | `"预印本论文"`

### 4.3 为什么 article_md5 改为可空

用户明确提到："并不是所有的文献论文数据都存在 article_md5 值"。虽然当前采样数据中都存在，但为了数据完整性，预留 NULL 空间。此时去重逻辑需要降级为 `doi` 或 `title + source + year` 组合判断。

### 4.4 为什么 links 合并 local_links

平台 PDF 预览链接（`local_links`）也是链接的一种，合并到 `links` JSON 中统一管理，类型可由 `name` 字段区分（如 `name: "平台PDF"`）。

### 4.5 date 字段格式不一致问题

| 类型 | 示例 | 格式 |
|------|------|------|
| 期刊论文 | `"2026"`, `"2020-04-15"` | yyyy 或 yyyy-MM-dd |
| 学位论文 | `"202507"` | yyyyMM |
| 预印本 | `"2026-5-6"` | yyyy-M-d（非零填充） |

当前保留 `VARCHAR(20)` 存原始值，`year` 字段统一提取年份用于分区和查询。后续可在应用层统一归一化。

---

## 五、迁移影响范围

需要同步修改的文件：

| 文件 | 修改内容 |
|------|----------|
| `sql/schema.sql` | 完整替换为新 DDL |
| `academic_spiders/items.py` | 删除 `type/cn_type/lang/is_free/semantic_entities/license/source_list/attachments/local_links`；新增 `contrib_institutions/subject_classification` |
| `academic_spiders/utils/parsers.py` | 删除旧字段映射，新增新字段映射；links 合并 local_links |
| `academic_spiders/pipelines.py` | 删除 `_upsert_extended_data()` / `_upsert_thesis_info()`；articles upsert 新增字段；authors 新增 author_id |

---

## 六、待确认事项

1. **subject_classification** 字段：`classification_bg` 是否确实有分析价值？从数据看对学科分类很有用（如"应用心理学""电脑、计算机"）。
2. **author_id** 是否需要？它来自 `author_id[]` 并行数组，当前预印本等类型中为空，但期刊论文中都有。可用于未来作者去重。
3. **abstracts** 是否需要同时存储英文摘要？当前响应数据中未发现英文摘要字段。
4. **article_md5 可空**后，去重策略需要改为 DOI 优先 → title+year+source 组合判断，是否可接受？
