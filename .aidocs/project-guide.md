# 公益学术平台(pubscholar.cn) 文献爬虫系统 — 项目文档

**版本**: 3.3 | **日期**: 2026-08-13

---

## 1. 项目概述

基于 Scrapy 框架构建的 pubscholar.cn 学术文献数据采集系统。

| 接口 | URL | 认证 | 数据量 | 状态 |
|------|-----|------|--------|------|
| v1 (开放) | `POST /hky/open/resources/api/v1/articles` | pub_ticket + XSRF-TOKEN | ~7400万中文文献 | ✅ 生产可用 |
| v2 (登录) | `POST /hky/api/v2/resources/article` | 需 scholarin.cn 专属 Cookie | 按关键词搜索 | ⏸️ 暂缓 |

> **注意 (2026-08-07)**: 登录后网站实际使用 v1 接口进行搜索，v2 接口的行为变化待进一步观察。详见 `.aidocs/troubleshooting-record.md#7`。

**核心技术点**：
- SHA1 签名反爬对抗（逆向自前端 Webpack 打包代码）
- 设备指纹 (x-finger) 模拟
- 同源请求头 (Sec-Fetch-Site) 伪造
- CSRF Token (XSRF-TOKEN) 管理
- CSTCloud Passport 登录自动化

---

## 2. 项目结构

```
academic-spiders/
├── scrapy.cfg                          # Scrapy 部署配置
├── pyproject.toml                      # uv 依赖管理
├── cookies.json                        # Cookie 配置 (gitignore)
├── cookies.json.example                # Cookie 配置模板
├── check_cookies.py                    # Cookie 健康检查 + 自动登录工具
│
├── sql/
│   └── schema.sql                      # 数据库建表脚本 (6 张表)
│
├── academic_spiders/                   # Scrapy 项目包
│   ├── items.py                        # ArticleItem 数据模型 (31 fields)
│   ├── settings.py                     # 全局配置 (从 cookies.json + 环境变量加载)
│   ├── middlewares.py                  # 签名注入 + Cookie 注入 + 过期检测中间件
│   ├── pipelines.py                    # MySQL (6表) + JSON 双管道 + spider_run_log
│   ├── utils/
│   │   ├── signing.py                  # 签名工具 (nonce/timestamp/SHA1/finger)
│   │   ├── parsers.py                  # 统一字段解析 (API record → ArticleItem)
│   │   ├── cookie_config.py            # Cookie 加载器 (文件 + 环境变量)
│   │   └── auth.py                     # CSTCloud Passport 自动登录模块
│   └── spiders/
│       ├── pubscholar_v1.py            # v1 全量爬虫 (spider_opened signal 驱动)
│       └── pubscholar_v2.py            # v2 搜索爬虫 (待验证)
│
├── run_v1_spider.py                    # 备选运行器 (requests 直连)
├── run_v2_spider.py                    # 备选运行器 (requests 直连)
├── test_v1_api.py                      # API 连通性诊断工具
│
├── result/                             # v1 接口抓包样本
├── .aidocs/                            # 项目文档与逆向分析
├── output/                             # JSON 输出目录 (gitignore)
└── task.md                             # 任务列表
```

---

## 3. 运行方式

### 3.1 使用 Scrapy (推荐)

```bash
# v1 — 测试 (3 页)
scrapy crawl pubscholar_v1 -s V1_MAX_PAGES=3

# v1 — 全量爬取中文文献 (~7400万条, ~3.5 天)
scrapy crawl pubscholar_v1

# v1 — 断点续爬
scrapy crawl pubscholar_v1 -s V1_START_PAGE=10000

# v2 — 关键词搜索 (需 scholarin.cn 登录 Cookie)
scrapy crawl pubscholar_v2 -a query="人工智能" -s V2_MAX_PAGES=10
```

### 3.2 Cookie 管理

```bash
# 启动前检查 Cookie 有效性
python check_cookies.py check

# 自动登录获取 Cookie (CSTCloud Passport)
python check_cookies.py login -u <账号> -p <密码>

# 手动更新: 编辑 cookies.json
```

### 3.3 备选运行器

```bash
python run_v1_spider.py -p 3 -s 10 --no-mysql
python run_v2_spider.py -q "人工智能" --cookie "..." --xsrf-token "..." --uid "..."
```

### 3.4 API 诊断

```bash
python test_v1_api.py
```

### 3.5 调试

#### 方式 1: DEBUG 日志 (最快, 不改代码)

```bash
# Scrapy + 测试库 + DEBUG 日志 + 只爬 1 页
scrapy crawl pubscholar_v1 \
  -s MYSQL_DATABASE=academicdb_test \
  -s LOG_LEVEL=DEBUG \
  -s V1_MAX_PAGES=1

# runner + 测试库 + verbose
python run_v1_spider.py -p 1 -s 3 --db-name academicdb_test -v
```

DEBUG 日志输出: 每个请求的 HTTP 状态、翻页进度、错误与限流信息。每条文献只记一行摘要 (页码/标题/去重键)，完整 JSON 数据保存在 `output/` 目录 (JsonExportPipeline)，日志中不再重复输出完整字段。

#### 方式 2: VSCode 断点调试 (推荐)

项目内置 [.vscode/launch.json](../../.vscode/launch.json) 三个配置:

| 配置 | 用途 |
|------|------|
| 调试 pubscholar_v1 (测试库) | Scrapy 爬虫 + 测试库 + DEBUG + 1 页 |
| 调试 run_v1_spider (测试库) | runner + 测试库 (同步代码, 调试体验最佳) |
| 调试 pubscholar_v1 (生产库, 慎用) | 仅确认安全时使用 |

使用步骤: 代码行号左侧设断点 → `F5` → 选择配置 → 启动。

推荐断点位置:

| 位置 | 观察内容 |
|------|----------|
| `pubscholar_v1.py` `parse()` | 翻页逻辑、响应解析 |
| `parsers.py` `record_to_item()` | 字段映射、dedup_key 生成 |
| `pipelines.py` `_upsert_article()` | 去重写入、审计逻辑 |
| `middlewares.py` `process_request()` | 签名注入 |

> 调试体验建议: 优先用「调试 run_v1_spider」——runner 是同步代码, 断点/单步/变量查看直观; Scrapy 是 Twisted 异步引擎, 断点命中但调用栈更深。

#### 方式 3: 代码内 breakpoint()

```python
# 在要调试的位置插入
breakpoint()   # 程序运行到此处暂停, 进入 pdb 交互模式
```

```bash
python run_v1_spider.py -p 1 -s 3 --db-name academicdb_test
```

pdb 命令: `p` 打印变量 / `n` 下一行 / `s` 进入函数 / `c` 继续 / `q` 退出。

#### 调试四件套

| 保护 | 参数 | 作用 |
|------|------|------|
| 测试库 | `-s MYSQL_DATABASE=academicdb_test` / `--db-name academicdb_test` | 数据不污染生产库 |
| 限制页数 | `-s V1_MAX_PAGES=1` / `-p 1` | 只跑 1 页, 快速出结果 |
| DEBUG 日志 | `-s LOG_LEVEL=DEBUG` / `-v` | 看全链路细节 |
| 小页面 | `-s V1_PAGE_SIZE=3` / `-s 3` | 响应小好分析 |

### 3.6 开发 vs 生产环境

同一个爬虫 (`pubscholar_v1` / `run_v1_spider.py`)，通过**数据库名**区分环境，无需两套代码。

| 环境 | 数据库名 | 日志目录 | 典型用途 |
|------|----------|----------|----------|
| 开发/测试 | `academicdb_test` (或其他非 `academicdb`) | `logs/test/` | 调试、验证字段、小批量试跑 |
| 生产 | `academicdb` (默认) | `logs/` | 全量爬取 ~7400 万条 |

**切换命令**：

```bash
# 开发 (环境变量方式: 数据 + 日志同时隔离)
$env:MYSQL_DATABASE="academicdb_test"
scrapy crawl pubscholar_v1 -s LOG_LEVEL=DEBUG -s V1_MAX_PAGES=1

# 生产 (默认库, 全量)
scrapy crawl pubscholar_v1
python run_v1_spider.py --all
```

**实现原理 (三层隔离)**：

1. **环境开关**: `settings.py` 中 `MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "academicdb")`，这是"环境"的唯一定义来源。
2. **数据层**: `academicdb` 与 `academicdb_test` 是两个独立 database，表结构一致 (同一个 `sql/schema.sql`)。MySQLPipeline / SpiderRunLogPipeline / resume.py 都从 settings 读库名，自动跟随。
3. **日志层**: `logging_config.py` 的 `is_test_db()` 判断库名 ≠ `academicdb` → 日志写 `logs/test/`，否则 `logs/`。

> **注意**: Scrapy 的 `-s MYSQL_DATABASE=...` 只切数据层——`settings.py` 在模块加载早期读环境变量决定日志目录，所以用 `-s` 时日志仍进 `logs/`。要连日志一起隔离，用环境变量或 runner 的 `--db-name`。

---

## 4. 配置说明

### 4.1 配置文件

| 层级 | 文件 | 说明 |
|------|------|------|
| Cookie | `cookies.json` | v1/v2 的 cookie/xsrf/finger/user_id (不提交 git) |
| 模板 | `cookies.json.example` | 配置模板，可安全提交 |
| 环境变量 | `PUBSCHOLAR_V1_COOKIE` 等 | 覆盖 cookies.json |
| 爬虫 | `settings.py` | 并发/延迟/MySQL 等爬虫参数 |

### 4.2 爬虫参数

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `PUBSCHOLAR_SECRET` | SHA1 签名密钥 | `6m6pingbinwaktg227gngifoocrfbo95` |
| `CONCURRENT_REQUESTS` | 并发数 | 8 |
| `DOWNLOAD_DELAY` | 请求间隔 (秒) | 1.5 |
| `AUTOTHROTTLE_ENABLED` | 自适应限速 | True |
| `COOKIES_ENABLED` | Scrapy cookie jar | False (自行管理) |
| `RETRY_TIMES` | 重试次数 | 3 |
| `RETRY_HTTP_CODES` | 触发重试的状态码 | 429, 500, 502, 503, 504 |

### 4.3 长时间运行

| 项目 | 说明 |
|------|------|
| pub_ticket 有效期 | ~10 天（CSTCloud Passport 会话票据） |
| 全量爬取预估 | 1.5M 页 × 1.5s × 8并发 ≈ 3.5 天 |
| Cookie 需求 | 单次跑完全程，无需中途刷新 |
| 断点续爬 | `scrapy crawl pubscholar_v1 -s V1_START_PAGE=<N>` |
| Cookie 过期处理 | 中间件检测到 403 "第三方应用独立请求时" → 立即停止 + 提示更新 |

---

## 5. 数据库 (v3.2)

### 5.1 设计原则

- **仅保留文献自身属性字段**，剔除 pubscholar 平台特有标记
- **所有文献类型共用一张 articles 主表**，类型专属字段允许 NULL
- **extendEntity 中有价值字段提取到 articles**，无价值子字段随表一起删除
- **dedup_key 去重键**：二级降级策略，保证跨批次数据不重复

### 5.2 表结构

```
articles (1) ──── (N) article_authors
     │
     ├── (1) ──── (0..1) article_thesis_info   (仅 article_type="学位论文")
     └── (1) ──── (N) article_keywords

articles_audit_log   (去重审计, 记录被覆盖的旧数据快照)
spider_run_log       (爬虫运行统计)
```

### 5.3 articles 字段分类

| 分类 | 字段 | 所有类型共有? |
|------|------|:--:|
| 核心 | id, dedup_key, title, abstracts, article_type, lang, links | ✅ |
| 关键词 | key_words, cn_keywords, en_keywords | ✅ |
| 作者 | author_names, contrib_institutions | ✅ |
| 来源 | source | ✅ |
| 日期 | date, year | ✅ |
| 标识符 | cstr | ✅ |
| 期刊专属 | volume, issue, first_page, last_page, doi | ❌ |

### 5.4 去重策略 (v3.2)

**去重键生成（二级降级，`cstr` 不参与）**：

| 优先级 | 条件 | 生成规则 | 示例 |
|:--:|------|----------|------|
| ① | `doi` 非空 | `"doi:" + 小写doi` | `doi:10.1016/j.jgg.2025.06.005` |
| ② | 否则 | `"hash:" + md5(规范化title\|source\|year)` | `hash:31ce5b20724a...` |
| ③ | 都为空 | `NULL`（无法去重，直接插入） | - |

**规范化处理**：
- doi → strip + 小写（DOI 大小写不敏感）
- title → strip + 合并连续空白（`re.sub(r"\s+", " ", ...)`）

**冲突处理（UPDATE + 审计）**：

```
SELECT 是否已存在 (WHERE dedup_key = ?)
 ├─ 已存在 → 旧数据写 articles_audit_log → UPDATE articles
 └─ 不存在 → INSERT (ON DUPLICATE KEY UPDATE 兜底竞态)
```

**审计表 `articles_audit_log`**：记录每次去重命中的新旧数据快照（old_data / new_data JSON），用于验证阶段排查：
1. 去重是否真的命中了重复记录
2. 命中的两条记录是否真的是同一篇文献（去重键可靠性）

确认去重可靠后，可清空或删除此表。

### 5.5 建表

```bash
mysql -u root -p academicdb < sql/schema.sql
```

### 5.6 测试环境 (数据库完全隔离)

调试/测试时使用独立的测试库 `academicdb_test`，与生产库 `academicdb` 物理隔离、结构相同：

```bash
# ① 初始化测试库 (创建库 + 建表, 用同一个 schema.sql)
python init_test_db.py

# ② 重置测试库 (清空测试数据重建)
python init_test_db.py --reset
```

**三种切换方式**（任选其一）：

| 方式 | 命令 | 场景 |
|------|------|------|
| 环境变量 | `$env:MYSQL_DATABASE="academicdb_test"` 后正常启动 | 长时间测试会话 |
| Scrapy `-s` | `scrapy crawl pubscholar_v1 -s MYSQL_DATABASE=academicdb_test` | 单次测试 |
| runner 参数 | `python run_v1_spider.py --db-name academicdb_test` | runner 测试 |

**隔离保证**：测试库与生产库是两个独立 database；`SpiderRunLogPipeline`、断点续爬 (`resume.py`) 等所有组件都从 settings 读取 `MYSQL_DATABASE`，自动跟随切换，测试产生的数据、运行日志、审计记录全部落在测试库，不会污染生产库。

**日志隔离**：文件日志同样跟随数据库切换 — 生产库写 `logs/`，其他库写 `logs/test/` (由 `logging_config.py` 的 `is_test_db()` 判断)。注意: Scrapy 用 `-s MYSQL_DATABASE=...` 切换时，settings.py 在启动早期读取环境变量决定日志目录，推荐测试时同时设置 `$env:MYSQL_DATABASE="academicdb_test"` 环境变量，确保日志也落到 `logs/test/`。

### 5.7 存储估算

| 表 | 行数 | 大小 |
|----|------|------|
| articles | 7400万 | ~110GB |
| article_authors | 6亿 | ~170GB |
| article_keywords | 5亿 | ~95GB |
| article_thesis_info | 100万 | <1GB |
| articles_audit_log | 验证阶段少量 | - |
| **合计** | | **~376GB** |

---

## 6. 签名算法

```
nonce     = random(6 chars, A-Z + 0-9)
timestamp = Date.now()  (13位毫秒)
signature = SHA1(sorted([secret, timestamp, nonce]).join(""))
x-finger  = MD5(device_fingerprint)  (独立于 signature!)
```

**密钥来源**：逆向自前端 Webpack 打包的 `app.js` 模块 `qI5z`，32 位小写字母+数字。

| URL 条件 | 密钥 |
|----------|------|
| 包含 `/app/` | `foocrg227gng6m6fbo95inwakpingbti` |
| 不包含 `/app/` | `6m6pingbinwaktg227gngifoocrfbo95` |

---

## 7. Cookie 获取方法

### 7.1 自动登录 (推荐)

```bash
python check_cookies.py login -u <CSTCloud账号> -p <密码>
```

自动完成 passport.escience.cn 登录 → 获取 pub_ticket → 写入 cookies.json。

### 7.2 手动获取

1. 浏览器打开 `https://pubscholar.cn/` 并登录
2. F12 → Application → Cookies → `pubscholar.cn`
3. 复制 `XSRF-TOKEN` 和 `pub_ticket` 的值
4. 更新 `cookies.json`:
   ```json
   {
     "v1": {
       "cookie": "XSRF-TOKEN=<值>; pub_ticket=<值>",
       "xsrf_token": "<XSRF-TOKEN值>"
     }
   }
   ```

### 7.3 过期处理

Cookie 过期后 API 返回 403，爬虫自动停止并显示：
```
Cookie 已过期! API 返回: {"cause":"第三方应用独立请求时，无此操作权限","failure":true}
请重新获取 Cookie:
  方式一: python check_cookies.py login -u <账号> -p <密码>
  方式二: 手动访问 https://pubscholar.cn 登录后更新 cookies.json
```

---

## 8. 变更记录

| 日期 | 版本 | 内容 |
|------|------|------|
| 2026-08-06 | v1.0 | 初版: 逆向分析、Scrapy 项目搭建、数据库设计 |
| 2026-08-07 | v2.0 | Scrapy Windows 兼容性修复、代码重构 (parsers.py)、Cookie 管理规范化 (cookies.json)、自动登录模块 (auth.py)、spider_run_log 自动写入 |
| 2026-08-12 | v3.0 | 数据库 v3: 删除 article_extended_data / type / cn_type / is_free; extendEntity 有价值字段提取到 articles; article_authors 新增 author_id; article_md5 改为 NULLABLE; links 合并 local_links |
| 2026-08-13 | v3.1 | 删除所有表的 article_md5 字段 (可从 PDF 文件名推导); parsers 合并 author_id[] 到 authors[]; 修复 year 提取逻辑 |
| 2026-08-13 | v3.2 | 去重逻辑: articles.dedup_key (二级降级: doi → title+source+year 哈希); 新建 articles_audit_log 审计表 (记录被覆盖旧数据); pipelines 去重写入 (SELECT→审计+UPDATE / INSERT) |
| 2026-08-13 | v3.3 | 日志: ① 文件日志 50MB 轮转 × 10; ② 测试/生产日志隔离 (logs/ 与 logs/test/); ③ 自定义 ConciseLogFormatter — 每条文献只记一行摘要 (页码/标题/去重键), 不再打印完整 item dict; ④ 类型检查: pyproject 增加 [tool.pyright] (basic 模式抑制动态类型噪音), 修复 27 处类型标注缺陷 (Optional/返回类型/`json.loads(response.text)` 替代 `.json()` 等) |
