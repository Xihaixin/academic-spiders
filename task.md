# 📋 公益学术平台(pubscholar.cn) 文献爬虫系统 — 任务列表

**更新日期**: 2026-08-25

---

## 项目背景
- **目标接口**: v1 (`/hky/open/resources/api/v1/articles`) 和 v2 (`/hky/api/v2/resources/article`)
- **数据量**: ~7400万条中文文献 (v1 全量), v2 按关键词搜索
- **技术栈**: Scrapy 2.17 + Python 3.12 + MySQL 8.0

---

## 已完成

### ✅ 1. Scrapy Windows 兼容性修复
- **问题**: `start_requests()` 生成器不被 asyncio reactor 调度; `CookiesMiddleware` 清除注入的 Cookie header
- **修复**: 改用 `spider_opened` 信号 + `engine.crawl()`; `COOKIES_ENABLED = False`
- **验证**: `scrapy crawl pubscholar_v1 -s V1_MAX_PAGES=3` → 150 items 成功

### ✅ 2. 数据库表结构
- 6 张表: `articles`, `article_extended_data`, `article_thesis_info`, `article_authors`, `article_keywords`, `spider_run_log`
- SQL 脚本: `sql/schema.sql`

### ✅ 3. Scrapy 项目结构
- `items.py`, `pipelines.py`, `settings.py`, `middlewares.py`, `utils/signing.py`
- Spiders: `pubscholar_v1.py`, `pubscholar_v2.py`

### ✅ 4. 聚合分桶爬取 (v3.4, 2026-08-25)
- **问题**: 单查询存在 offset 10000 条窗口上限 (page×size ≤ 10000), 线性翻页只能拿到前 10000 条
- **验证**: `fetch_aggregations.py` / `verify_window_limit.py` — 确认窗口按查询重置、year 完备、subject 单值但 top-100 截断、窄上下文 source 完备
- **实现**: `pubscholar_v1.py` 双模式 — 分桶 (collection→year→subject→source 递归切分, 逐桶滑窗爬取), 线性模式保留
- **记录器**: `crawl_query_state` (桶状态/进度) + `crawl_plan` (计划标记) + `utils/query_state.py`
- **覆盖率**: 北大核心 ~92.5% / 南大核心 ~87.7% (残差为 subject top-100 外, 按需求接受)
- **断点续爬**: query_hash 幂等 + running→pending 重置 + 计划跳过重建
- 完整过程: `.aidocs/academic-spiders/bucket-crawl-implementation-record.md`

---

## 待执行任务

### 🔴 高优先级

| # | 任务 | 说明 |
|---|------|------|
| **H1** | 消除代码重复: `_parse_record` / `_record_to_item` | `run_v1_spider.py:138` 和 `pubscholar_v1.py:181` 有 ~60 行重复字段映射，应收敛到 `utils/parsers.py`，两处统一引用 |
| **H2** | 实现 `spider_run_log` 写入 | Pipeline 启动/结束时自动写入运行日志 (run_id UUID, 起止时间, total_items, last_page) |
| **H3** | Cookie 管理规范化 | 移除 `settings.py` 中硬编码的 Cookie 默认值，改为 `cookies.json` 或 `COOKIE` 环境变量；v1/v2 独立配置 |

### 🟡 中优先级

| # | 任务 | 说明 |
|---|------|------|
| **M1** | Middleware/Pipeline 弃用警告修复 | `process_request(self, request, spider)` → 通过 `self.crawler` 获取 spider，消除 Scrapy 2.17 弃用警告 |
| **M2** | 修复双重重试冲突 | `PubscholarRetryMiddleware` 和 `RetryMiddleware` 均拦截 403/429，导致 `retry/max_reached: 2`（重复计数） |
| **M3** | v2 Spider 集成验证 | 暂缓 — 观察发现登录后网站使用 v1 而非 v2 接口 (详见 `.aidocs/troubleshooting-record.md#7`) |

### ❓ 待观察

| # | 任务 | 说明 |
|---|------|------|
| **O1** | v1/v2 接口行为变化 | 登录后实际使用 v1 而非 v2 接口 (2026-08-07 观察)。待后续确认是否为永久性变更后再决定 v2 去留 |

### 🟢 低优先级

| # | 任务 | 说明 |
|---|------|------|
| **L1** | v1 Cookie 过期指引 | 当前 `V1_COOKIE` 为浏览器会话 Cookie，过期后需从 pubscholar.cn 重新获取，补充文档说明 |

---

## 数据结构审查结论

| 审查项 | 状态 |
|--------|------|
| Item 字段 ↔ API 响应 | ✅ 34 字段全部映射 |
| Item → Pipeline INSERT | ✅ 字段一一对应 |
| Pipeline → SQL schema | ✅ 列数匹配 |
| spider_run_log 写入 | ❌ 表已建但 Pipeline 未写入 (见 H2) |

---

## 改动文件清单 (本轮已提交)

| 文件 | 改动内容 |
|------|----------|
| `settings.py:10` | `COOKIES_ENABLED = False` |
| `spiders/pubscholar_v1.py` | `start_requests()` → `_on_spider_opened()` signal |
| `spiders/pubscholar_v2.py` | `start_requests()` → `_on_spider_opened()` signal |
| `middlewares.py` | `_retry()` 签名适配 Scrapy 2.17 |
| `test_v1_api.py` | 适配 `build_signature_headers()` finger 参数 |
| `.aidocs/project-guide.md` | 修正运行方式为 `scrapy crawl` |
| `.aidocs/troubleshooting-record.md` | 修正根因分析 |

## 改动文件清单 (v3.4 分桶模式, 未提交)

| 文件 | 改动内容 |
|------|----------|
| `sql/schema.sql` | 新增 `crawl_query_state` / `crawl_plan` 两张表 |
| `academic_spiders/utils/api_client.py` | (新) 轻量 API 客户端 (签名+Cookie+聚合/文章接口) |
| `academic_spiders/utils/query_plan.py` | (新) 分桶切分维度/纯函数 |
| `academic_spiders/utils/query_state.py` | (新) 桶状态 CRUD (持久连接 + 批量插入 + 计划标记) |
| `academic_spiders/spiders/pubscholar_v1.py` | 双模式: 线性 + 分桶 (聚合驱动, 桶状态/断点续爬) |
| `academic_spiders/settings.py` | 新增 `V1_BUCKET_*` 分桶配置 |
| `academic_spiders/utils/parsers.py` | 修复 `date` 截断 (VARCHAR(10)) |
| `fetch_aggregations.py` | (新) 验证工具: 抓聚合响应存 JSON |
| `verify_window_limit.py` | (新) 验证工具: 窗口探测 + 分桶可行性预览 |
| `.aidocs/academic-spiders/bucket-crawl-implementation-record.md` | (新) 分析与实现全记录 |
| `.aidocs/project-guide.md` | v3.4 章节: 分桶模式/配置/数据库/变更记录 |
