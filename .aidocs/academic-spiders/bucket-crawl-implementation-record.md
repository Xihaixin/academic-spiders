# 公益学术平台 v1 聚合分桶爬取 — 分析与实现全记录

**日期**: 2026-08-25 | **分支**: `debug/scrapy_spider` | **环境**: Windows + Python 3.12 + Scrapy 2.17 + MySQL 8.0 (开发库 `academicdb_test`)

> 本文档完整记录从"分页窗口受限"问题出发，经需求澄清、可行性验证、方案设计、代码实现到测试验证的整个过程。
> 相关文档: [任务背景](./post_articles_aggregations.md) · [项目指南](../project-guide.md) · [排障记录](../troubleshooting-record.md)

---

## 目录

- [1. 任务背景与问题](#1-任务背景与问题)
- [2. 需求澄清与确认](#2-需求澄清与确认)
- [3. 验证阶段：关键发现](#3-验证阶段关键发现)
- [4. 设计方案](#4-设计方案)
- [5. 实现细节](#5-实现细节)
- [6. 开发中遇到的问题与解决方案](#6-开发中遇到的问题与解决方案)
- [7. 测试与验证结果](#7-测试与验证结果)
- [8. 使用方法](#8-使用方法)
- [9. 已知问题与注意事项](#9-已知问题与注意事项)
- [10. 结论与后续建议](#10-结论与后续建议)

---

## 1. 任务背景与问题

### 1.1 现状

v1 开放接口 `POST /hky/open/resources/api/v1/articles`，请求体 `lang=C`（中文文献）时全库约 **7454 万条**。原爬虫从 `page=1, size=50` 顺序翻页。

### 1.2 问题

**page=200 之后无法再获取数据**，响应 HTTP 200 但内容为空：

```json
{"total":0,"is_last":true,"content":[]}
```

即单次查询存在"分页窗口"上限，无法直接翻完整个库。

### 1.3 思路

聚合接口 `POST /hky/open/resources/api/v1/articles/aggregations` 返回每个筛选维度的可选值与计数。设想：**用筛选条件把 7454 万条切分成若干小桶（每桶命中数 ≤ 窗口上限），逐桶爬完即可覆盖全量**；桶间重叠靠已有去重机制兜底。

### 1.4 任务需求（原文要点）

1. 再次验证 `lang=C, page>200` 后的爬虫响应情况
2. 获取 aggregations 响应结果并存为 JSON 文件
3. 设计一个"记录器"，可调度多条件查询组合的执行，记录进度与已发送的查询参数

设计重点：多条件组合规则、进度记录、断点续爬（端点重续）。

---

## 2. 需求澄清与确认

经与需求方确认，约束如下：

| 项 | 结论 |
|----|------|
| 数据范围 | 只取**中文核心期刊**：collection ∈ {**北大核心**, **南大核心**}，lang 固定 **C（中文）** |
| 混入选项 | collection 与 lang 两个维度**不混入其它选项** |
| 其它维度 | year/subject/source 等无特殊限制，走递归分治 |
| 覆盖率 | **不必 100%，拿到绝大多数即可**（放弃 subject top-100 之外约 8% 残差） |
| 记录器 | **MySQL 新表**（`crawl_query_state`） |
| 实现范围 | **只改 Scrapy**（`pubscholar_v1.py`），runner 不改 |
| 旧模式 | **保留线性翻页模式**，配置开关切换 |
| 开发环境 | `.env` 的 `MYSQL_DATABASE=academicdb_test`（数据/日志隔离） |
| 分支 | `debug/scrapy_spider` |

---

## 3. 验证阶段：关键发现

### 3.1 窗口限制 = offset 10000 条/查询 ✅

用三个不同 `size` 探测边界，确认限制基于 **offset（page×size ≤ 10000）**，与页大小无关：

| size | 正常 | 超限 |
|------|------|------|
| 50 | page 200（offset 9950-9999） | page 201（offset 10000）→ 空 |
| 100 | page 100 | page 101 → 空 |
| 10 | page 1000 | page 1001 → 空 |

**超限响应特征**：`total=0, is_last=true, content=[], total_pages=0`（与"自然结束"可通过 `total_pages` 区分）。

### 3.2 换过滤条件后窗口重置 ✅（方案成立的前提）

| 查询 | total | 结果 |
|------|-------|------|
| 北大核心（8,081,930） | 161,639 页 | page 200 正常 → 201 超限 |
| 北大核心 + year=2020（6,846） | 137 页 | page 200 自然结束（不触发窗口） |
| 北大核心 + 2020 + 医药卫生（64） | 2 页 | 正常翻完 |

→ **每个不同的过滤组合各自拥有独立的 10000 条窗口**，分桶遍历可突破单查询限制。

### 3.3 维度完备性（决定分桶方案）

| 维度 | 覆盖情况 | 结论 |
|------|----------|------|
| `year` | 基础 108 年计数和=100%、北大 94 年=100%、南大 72 年=100% | **唯一完备划分维度** |
| `subject` | 单值，但被 **top-100 截断**（北大核心覆盖 91.4%，南大 87.3%） | 可切分，残差放弃 |
| `source` | 基础库仅覆盖 8.2%（严重截断） | 不可做全局切分 |
| `keyword` / `institution` / `funding` / `correspAuthor` | 均 top-100 截断 | 不参与切分 |
| `type` | 4 值，99.8%（期刊论文占 99%+） | 几乎完备但太粗 |
| `source`（窄上下文内） | 北大+2018+信息与知识传播：56 个 source，计数和≈total | **窄上下文内完备** → 可回收超大桶 |

**subject 单值性验证**：`subject=A,B,C`（逗号多选）的总计数 == 各 subject 单查计数之和（444,943 == 444,943）→ 每篇文献只有一个 subject，分桶无重叠。

### 3.4 聚合接口行为限制

| 现象 | 结论 |
|------|------|
| 每上下文聚合列表最多 ~100 个值（year 除外，返回 108 个） | 聚合列表被服务端截断 |
| `page≠1` 或 `size≠10` 的聚合请求挂起（ReadTimeout 60s+） | **聚合接口只接受 page=1/size=10**，无法分页枚举 |
| 跨上下文（换 year、换 collection）可发现更多 subject（并集 155 个） | 可部分枚举但无法保证完整 |
| 北大核心 2009 年用 149 学科并集查询覆盖率 94.0% | 剩余 ~6% 为 top-100 外学科，放弃 |

### 3.5 分桶可行性预览（真实调用聚合接口模拟递归切分）

**阈值 9900 / size 50**：

| 切分深度 | 集合 | 叶子桶 | 超大桶 | 计划覆盖率 | 可获取覆盖率 | 翻页请求数 | 预估耗时(5req/s) |
|:--:|---|:--:|:--:|:--:|:--:|:--:|:--:|
| 2 (year→subject) | 北大核心 | 3,765 | 85 | 92.54% | 88.39% | 144,848 | ~8h |
| 2 | 南大核心 | 2,589 | 8 | 87.70% | 86.84% | 30,108 | ~1.7h |
| **3 (year→subject→source)** | 北大核心 | **6,805** | **0** | **92.54%** | **92.54%** | 153,172 | ~8.5h |
| **3** | 南大核心 | **2,954** | **0** | **87.70%** | **87.70%** | 30,587 | ~1.7h |

→ depth=3 时超大桶全部被 source 级切分回收（窄上下文 source 完备），覆盖率 = 计划覆盖率（残差仅剩各年 subject top-100 之外，符合"绝大多数"要求）。

---

## 4. 设计方案

### 4.1 总体架构

```
爬虫启动 (V1_BUCKET_MODE=1)
  → 同步调用聚合接口构建分桶计划 (collection固定 → year → subject → source 递归切分)
  → 叶子桶写入 crawl_query_state (query_hash 幂等, 已存在跳过)
  → 记录计划完成标记 crawl_plan (续爬跳过重建)
  → 逐桶领取 (pending→running) → 桶内滑动翻页 (窗口并发)
  → 每页产出 Item (复用 record_to_item + MySQL/JSON 管道, 现有去重生效)
  → 桶完成/失败 → 状态落库 → 调度下一桶
  → 全部处理完 / 达到桶数上限 → 结束
```

### 4.2 分桶策略

- 顶层：collection ∈ {北大核心, 南大核心}，lang 固定 `C`
- 递归维度顺序：`year → subject → source`
- 叶子桶阈值：`9900`（窗口 10000 留余量），size=50 → 桶内最多 198 页
- 覆盖缺口（各年 subject top-100 之外）接受丢弃

### 4.3 记录器设计

**`crawl_query_state` 表**（每行 = 一个查询桶）：

| 字段 | 说明 |
|------|------|
| `query_hash` | 11 个聚合键规范化 MD5，唯一标识一个查询桶（幂等 + 断点续爬基础） |
| `query_params` | 筛选参数 JSON（collection/lang/year/subject/source...） |
| `total` / `max_page` | 聚合计数 / 桶内翻页边界 |
| `status` | pending / running / completed / failed |
| `cur_page` / `items_collected` | 进度 |
| `run_id` | 最近处理它的运行批次 |

**`crawl_plan` 表**：记录"集合+阈值+深度"哈希对应的计划已完整构建，续爬时跳过重建（省约 2 分钟）。

### 4.4 查重

复用现有 `dedup_key` 二级降级（doi → title+source+year 哈希）与 `pipelines.py` 的 SELECT→审计+UPDATE 管道。北大/南大重叠、跨批次重复自动消重，无需新设计。

### 4.5 翻页边界

```
max_page = min(ceil(total / size), threshold // size)   # 如 9900//50 = 198
```

桶内从 page=1 滑窗翻页；`is_last=true` 或 `page >= max_page` 结束；异常空响应（total_pages=0）重试 5 次后整桶失败。

### 4.6 断点续爬

- `query_hash` 幂等插入，已完成桶保留
- 启动时 `running → pending` 重置（上次异常终止的桶续爬）
- `crawl_plan` 标记存在 → 跳过计划重建，直接续爬
- 桶级 `cur_page`/`items_collected` 落库

---

## 5. 实现细节

### 5.1 改动文件清单

| 文件 | 类型 | 内容 |
|------|------|------|
| `sql/schema.sql` | 改 | 新增 `crawl_query_state`、`crawl_plan` 两张表 |
| `academic_spiders/utils/query_state.py` | 新 | 桶状态 CRUD（持久连接 + 批量插入 + 计划标记） |
| `academic_spiders/utils/query_plan.py` | 新 | 分桶常量与纯函数 |
| `academic_spiders/utils/api_client.py` | 新 | 轻量 API 客户端（验证脚本/计划构建共用） |
| `academic_spiders/spiders/pubscholar_v1.py` | 改 | 双模式：线性（原逻辑）+ 分桶 |
| `academic_spiders/settings.py` | 改 | `V1_BUCKET_*` 分桶模式配置 |
| `academic_spiders/utils/parsers.py` | 改 | `date` 截断为 10 位 |
| `fetch_aggregations.py` | 新 | 阶段0：拉取聚合响应存 JSON |
| `verify_window_limit.py` | 新 | 阶段0：窗口探测 + 分桶可行性预览 |

### 5.2 数据表设计

**crawl_query_state**：

```sql
CREATE TABLE `crawl_query_state` (
    `id`                BIGINT NOT NULL AUTO_INCREMENT,
    `run_id`            VARCHAR(36)     NOT NULL,
    `query_hash`        VARCHAR(64)     NOT NULL COMMENT '查询参数规范化MD5 (唯一)',
    `query_params`      JSON            NOT NULL COMMENT '筛选参数 (aggregations对象)',
    `collection`        VARCHAR(50)     NULL,
    `total`             BIGINT          DEFAULT 0,
    `page_size`         INT             DEFAULT 50,
    `max_page`          INT             DEFAULT 0,
    `status`            VARCHAR(20)     DEFAULT 'pending',
    `cur_page`          INT             DEFAULT 0,
    `items_collected`   BIGINT          DEFAULT 0,
    `start_time` / `end_time` / `error_message` ...,
    UNIQUE KEY `uk_query_hash` (`query_hash`),
    INDEX `idx_status`, `idx_run_id`, `idx_collection`
) COMMENT='查询桶状态表';
```

**crawl_plan**：

```sql
CREATE TABLE `crawl_plan` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `plan_key`      VARCHAR(64) NOT NULL COMMENT '集合+阈值+深度 哈希',
    `collections`   VARCHAR(255) NOT NULL,
    `threshold`     INT NOT NULL, `depth` INT NOT NULL,
    `bucket_count`  INT DEFAULT 0,
    `created_at`    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_plan_key` (`plan_key`)
) COMMENT='分桶计划标记表';
```

### 5.3 爬虫流程（`pubscholar_v1.py`）

- `_on_spider_opened`：分桶模式 → `_build_plan_and_start()`；线性模式 → 原有 `engine.crawl` 注入
- `_build_plan_and_start`：已有计划标记则跳过重建；否则同步构建 → `plan_mark` → 调度
- `_plan_recurse`：递归切分，叶子入 `_plan_batch`（每 500 条批量入库）
- `_try_dispatch_buckets` / `_claim_and_start_bucket`：填满并发桶数，领取 pending 桶
- `_issue_pages`：桶内滑动窗口（`bucket_window` 个在途请求）
- `parse_bucket_page`：产出 Item、滑窗续页、桶完成/失败调度下一桶、异常重试
- `_on_spider_closed`：释放持久连接

### 5.4 配置项（settings.py）

| 配置 | 默认 | 说明 |
|------|------|------|
| `V1_BUCKET_MODE` | 0 | 1=分桶模式，0=线性模式 |
| `V1_BUCKET_COLLECTIONS` | `北大核心,南大核心` | 顶层 collection 集合（支持 `,` `，` `、` 分隔） |
| `V1_BUCKET_THRESHOLD` | 9900 | 叶子桶阈值 |
| `V1_BUCKET_DEPTH` | 3 | 切分深度（year→subject→source） |
| `V1_BUCKET_WINDOW` | 4 | 桶内并发在途请求数 |
| `V1_BUCKET_CONCURRENCY` | 2 | 同时爬取的桶数 |
| `V1_BUCKET_MAX_BUCKETS` | None | 测试用：限制本次爬取桶数 |
| `V1_BUCKET_FORCE_PLAN` | 0 | 1=强制重建分桶计划 |

---

## 6. 开发中遇到的问题与解决方案

### 问题 1：Scrapy 下载器对聚合接口挂起（~86s/请求）

**现象**：分桶计划的聚合请求经 Scrapy 下载器发送，每个请求约 86s 才返回（甚至 3 分钟），而用 `requests` 直连聚合接口 <1s。

**排查**：独立脚本测序连/并发聚合请求均 <6s → 排除服务端限流；确认是 Scrapy/Twisted 客户端与该聚合端点的兼容问题（articles 接口经 Scrapy 正常）。

**解决**：**计划构建改用 `api_client`（requests）同步阻塞构建**，绕开 Scrapy 下载器。计划构建期约 1-3 分钟、期间无其它请求，阻塞可接受；桶爬取仍走 Scrapy。

### 问题 2：叶子桶逐条插入 MySQL 极慢（每个大年份 3 分钟）

**现象**：计划构建每个大年份有 ~90 个子科目桶，`insert_bucket` 每条新建一个 MySQL 连接（~2s/条），一个年份 90 条即 3 分钟。

**解决**：`QueryStateStore` 改为**持久连接 + `executemany` 批量插入**（每 500 条一批）。修复后计划构建总耗时 ~96s（南大核心）。

### 问题 3：`date` 字段超长写入失败

**现象**：部分记录 date 返回 `"2023-06-15 00:00:00"`，超过 `articles.date VARCHAR(10)`。

**解决**：`parsers.py` 截断为 `[:10]`（`YYYY-MM-DD` 前缀）。

### 问题 4：续爬时重复重建计划

**现象**：每次重启都重跑 ~2 分钟的计划构建。

**解决**：新增 `crawl_plan` 标记表，匹配当前集合+阈值+深度则跳过重建；`V1_BUCKET_FORCE_PLAN=1` 强制重建。

### 问题 5：collection 根聚合失败时误标计划完成

**解决**：跟踪 `plan_ok`，任一 collection 根聚合失败则不写计划标记，下次运行会重新构建该集合。

### 问题 6（验证期观察）：服务端临时性限流

**现象**：某段时间聚合请求逐个变慢（15s→3min），间隔后恢复 <1s。

**结论**：为近期大量请求触发的滚动限流，非持久状态。实际爬取时若命中，异常重试逻辑（5 次）会将桶标记失败，续爬时重试。

---

## 7. 测试与验证结果（`academicdb_test`）

### 7.1 分桶计划构建

- 南大核心：**2597 个叶子桶，~96s**，聚合接口调用 ~40 次
- 幂等：重复运行 INSERT IGNORE 不产生重复桶

### 7.2 桶爬取

| 桶 | 计数 | 页数 | 结果 |
|----|-----:|-----:|------|
| 2026 | 326 | 7 | ✓ |
| 2025 | 343 | 7 | ✓ |
| 2021 | 49 | 2 | ✓ |
| 2020 | 706 | 15 | ✓ |
| 2019 + 信息与知识传播 | 6,267 | 126 | ✓ |
| 2019 + 教育 | 3,027 | 61 | ✓ |

**0 错误**，数据落库（articles / article_authors / article_keywords 均正常）。

### 7.3 断点续爬

- 二次运行自动跳过已完成桶，续爬下一批 pending 桶 ✓
- `crawl_plan` 标记存在时跳过计划重建，直接续爬 ✓
- 状态推进：completed×8 / pending×2589 ✓

### 7.4 数据质量说明

部分 2026/2025 南大核心记录的 `article_type` 为空——**API 本身返回空串**（`cn_type` 恒为"论文"，`type` 恒为"article"，无法推断细分类型），属站点数据问题，爬虫如实存储。

---

## 8. 使用方法

```bash
# 开发/测试（限 2 桶, 走测试库）
scrapy crawl pubscholar_v1 -s V1_BUCKET_MODE=1 -s V1_BUCKET_MAX_BUCKETS=2 -s MYSQL_DATABASE=academicdb_test

# 生产（北大核心 + 南大核心 全量, 默认配置）
scrapy crawl pubscholar_v1 -s V1_BUCKET_MODE=1

# 强制重建分桶计划（如更换 collection/阈值）
scrapy crawl pubscholar_v1 -s V1_BUCKET_MODE=1 -s V1_BUCKET_FORCE_PLAN=1

# 线性模式（原有行为, 默认）
scrapy crawl pubscholar_v1

# 验证工具
python fetch_aggregations.py --all-core --with-total   # 抓聚合响应存 JSON
python verify_window_limit.py --plan-only              # 分桶可行性预览
```

---

## 9. 已知问题与注意事项

1. **覆盖率**：北大核心 ~92.5%、南大核心 ~87.7%（depth=3）。缺口为各年 subject top-100 之外的残差（聚合接口无法完整枚举），按需求接受。
2. **性能**：当前接口单请求延迟 2-7s，实测吞吐 ~1.2 req/s（DOWNLOAD_DELAY=0.4 时）。据此估算南大核心 ~30k 请求约 7h、北大核心 ~153k 约 35h。实际受服务端响应速度影响，可通过调大 `V1_BUCKET_CONCURRENCY`/`V1_BUCKET_WINDOW` 与 `DOWNLOAD_DELAY` 平衡。
3. **临时限流**：连续大量请求可能触发服务端渐进式限流（响应 3 分钟级）；爬虫已用 5 次异常重试 + 桶失败续爬兜底。
4. **聚合接口限制**：只能 `page=1/size=10`，其它参数会挂起；每上下文聚合列表 top-100 截断。`verify_window_limit.py` 与 `fetch_aggregations.py` 已内置这些约束。
5. **runner 未改**：按"只改 Scrapy"决策，`run_v1_spider.py` 仅线性模式。
6. **生产库**：全量跑需切换到生产库 `academicdb`（`MYSQL_DATABASE=academicdb` 或去掉环境变量），并确保 `crawl_query_state`/`crawl_plan` 表已建（`sql/schema.sql`）。
7. **数据量估算**：全量中文核心约 808 万（北大）+165 万（南大）粗重，去重后净数据量以 articles 表为准。

---

## 10. 结论与后续建议

### 结论

- ✅ **前提成立**：单查询窗口 = offset 10000 条，且按查询重置 → 分桶遍历可行
- ✅ **方案落地**：collection → year → subject → source 递归分桶，覆盖率达标（绝大多数）
- ✅ **记录器/续爬**：`crawl_query_state` + `crawl_plan` 支撑调度、进度、断点续爬
- ✅ **去重**：复用现有 `dedup_key` 管道，跨桶/跨批次无重复
- ✅ **双模式**：线性模式原样保留，配置开关切换

### 后续建议

1. 生产全量前先跑少量桶验证生产库表结构（`crawl_query_state`/`crawl_plan`）
2. 观察限流边界，必要时调低并发/加大延迟
3. 若需 100% 覆盖 subject 残差，需另行研究（聚合接口不可枚举，暂无干净方案）
4. 可将 `verify_window_limit.py` 的分桶预览结果沉淀为正式的计划快照，供爬取前审计
