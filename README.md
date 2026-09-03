# academic-spiders

公益学术平台(pubscholar.cn / scholarin.cn) 学术文献数据采集系统。基于 Scrapy 框架，已破解 API SHA1 签名反爬机制，支持全量中文文献抓取和关键词检索。

**目标数据量**: ~7400 万条中文文献

---

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 创建数据库表

```bash
mysql -u root -p academicdb < sql/schema.sql
```

### 3. 运行爬虫

```bash
# v1 — 全量获取中文文献 (仅分桶模式, 突破单查询窗口限制)
scrapy crawl pubscholar_v1                          # 全量爬取 (北大+南大核心)

# v2 — 按关键词搜索 (需登录 Cookie)
scrapy crawl pubscholar_v2 -a query="人工智能"
```

---

## 开发 vs 生产环境 (三模式, v3.5)

同一套爬虫代码，通过**运行模式**切换不同的 MySQL 目标库与日志目录（数据 + 日志自动隔离）。

| 模式 | 数据库 | 主机 | 日志目录 | JSON 输出目录 | 用途 |
|------|--------|------|----------|---------------|------|
| `test` | `academicdb_test` | localhost | `logs/test/` | `output/test/` | 本地测试/调试 |
| `dev` | `academicdb` | localhost | `logs/dev/` | `output/dev/` | 本地开发 |
| `prod` | `pubscholar` | 远程主机 | `logs/` | `output/` | 远程生产库 |

### 模式切换 (推荐: env.py)

```bash
python env.py list                      # 查看所有模式 + 当前生效模式
python env.py current                   # 查看当前激活配置 (密码脱敏)
python env.py switch test               # 本地测试
python env.py switch dev                # 本地开发
python env.py switch prod               # 远程生产库 (会二次确认)
python env.py init                      # 首次使用: 从模板生成 .env.secrets
```

**实现原理 (配置类 + 注册表)**: 模式的具体值定义在代码子类中（`academic_spiders/config/modes.py`，
`ConfigBase` 定义共有结构）；`.env` 只保留单一开关 `ACADEMIC_MODE=<mode>`；注册表
`academic_spiders/config/registry.py` 依据该开关构建激活配置对象；`settings.py` 从配置对象
取 `MYSQL_*`、日志目录与 JSON 输出目录，现有管道/扩展零改动。

- **密钥隔离**: 密码、远程主机等敏感字段存 `.env.secrets`（gitignored）；模板 `.env.secrets.example` 可提交。
- **易扩展**: 新增模式 = 在 `modes.py` 加一个继承 `ConfigBase` 的子类 + 在 registry 注册 + 在 `.env.secrets` 加段。
- **环境变量临时覆盖**: 进程环境设置 `MYSQL_*` 可覆盖配置类值（优先级 环境变量 > secrets > 类默认）。
- **单次数据层覆盖**仍可用 `-s MYSQL_DATABASE=academicdb_test` 或 `--db-name`，日志目录仍跟随激活模式。

### 初始化测试库 (可选)

```bash
python init_test_db.py          # 创建 academicdb_test (结构同生产, 数据隔离)
python init_test_db.py --reset  # 重置测试库
```

**原理**: `ACADEMIC_MODE` 是单一模式开关（`.env` 中，由 `env.py switch` 维护）；`settings.py` 从激活配置对象（`config` 包）读取 `MYSQL_*` 等；所有写库组件（MySQL 管道 / 运行日志 / 断点续爬）都从 settings 取库名自动跟随；`logging_config.py` 按激活模式分流日志（`prod→logs/`、`dev→logs/dev/`、`test→logs/test/`）。

---

## 两个接口

| | v1 (开放) | v2 (登录) |
|---|---|---|
| URL | `pubscholar.cn/hky/open/resources/api/v1/articles` | `scholarin.cn/hky/api/v2/resources/article` |
| 认证 | 无需登录，需会话 Cookie | 需登录 Cookie |
| 功能 | 全量中文文献 (~7400万), 分桶模式 | 按关键词搜索 |
| 爬虫 | `scrapy crawl pubscholar_v1` | `scrapy crawl pubscholar_v2 -a query="..."` |

### 获取 Cookie

**v1** — 浏览器打开 https://pubscholar.cn/ (无需登录) → F12 → Application → Cookies → 复制 `XSRF-TOKEN` 和 `JSESSIONID`

**v2** — 浏览器登录 https://scholarin.cn/ → F12 → Network → 搜索一次 → 找到 API 请求 → 复制 Cookie / X-XSRF-TOKEN / uid

---

## 运行参数

### v1 分桶模式 (settings / `-s`)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `V1_BUCKET_COLLECTIONS` | 顶层 collection 集合 | `北大核心,南大核心` |
| `V1_BUCKET_THRESHOLD` | 单桶最大条数阈值 | `9900` |
| `V1_BUCKET_DEPTH` | 切分深度 (year→subject→source) | `3` |
| `V1_BUCKET_WINDOW` | 桶内滑动窗口 (并发页数) | `4` |
| `V1_BUCKET_CONCURRENCY` | 并发桶数 | `2` |
| `V1_BUCKET_MAX_BUCKETS` | 限爬桶数 (测试用, None=全部) | `None` |
| `V1_BUCKET_FORCE_PLAN` | 强制重建分桶计划 | `0` |

### v2 (settings / `-a`)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `query` | 搜索关键词 (**必填**, `-a query="..."`) | - |

### 诊断工具

```bash
python test_v1_api.py   # 验证 API 连通性和签名
```

---

## 调试

### 方式 1: DEBUG 日志 (最快)

```bash
# Scrapy + 测试库 + DEBUG 日志
scrapy crawl pubscholar_v1 -s MYSQL_DATABASE=academicdb_test -s LOG_LEVEL=DEBUG -s V1_BUCKET_MAX_BUCKETS=1
```

### 方式 2: VSCode 断点调试 (推荐)

已内置 [.vscode/launch.json](.vscode/launch.json) 配置:

| 配置 | 用途 |
|------|------|
| 调试 pubscholar_v1 (当前模式) | Scrapy + DEBUG, 数据库跟随当前 .env 模式 |
| 调试 pubscholar_v1 (测试, 限 10 桶) | Scrapy + 测试库常用调试, 数据库跟随当前 .env 模式 |

> 两个配置均通过 `envFile` 加载 `.env`（不再硬编码 MYSQL_*），所以调试**跟随 env.py 切换的模式**：
> 先 `python env.py switch <test|dev|prod>` 再按 F5，即写入对应模式的库。

使用: 代码行号左侧设断点 → `F5` → 选择配置 → 启动。推荐断点位置: `parse_bucket_page()` (桶内翻页)、`record_to_item()` (字段解析)、`_upsert_article()` (去重写入)、`process_request()` (签名注入)。

### 方式 3: 代码内 breakpoint()

在要调试的位置插入 `breakpoint()`，然后运行:

```bash
scrapy crawl pubscholar_v1 -s V1_BUCKET_MAX_BUCKETS=1
```

pdb 命令: `p` 打印变量 / `n` 下一行 / `s` 进入函数 / `c` 继续 / `q` 退出。

### 调试四件套

| 保护 | 参数 | 作用 |
|------|------|------|
| 测试库 | `-s MYSQL_DATABASE=academicdb_test` | 数据不污染生产库 |
| 限爬桶数 | `-s V1_BUCKET_MAX_BUCKETS=1` | 只跑 1 个桶 |
| DEBUG 日志 | `-s LOG_LEVEL=DEBUG` | 看全链路细节 |
| 小页面 | `-s V1_PAGE_SIZE=3` | 响应小好分析 |

---

## 项目结构

```
academic-spiders/
├── academic_spiders/               # Scrapy 项目包
│   ├── items.py                    # ArticleItem 数据模型
│   ├── settings.py                 # 全局配置
│   ├── middlewares.py              # 签名 + Cookie 注入中间件
│   ├── pipelines.py                # MySQL + JSON 双管道
│   ├── utils/signing.py            # SHA1 签名工具
│   └── spiders/
│       ├── pubscholar_v1.py        # v1 全量爬虫 (分桶模式)
│       └── pubscholar_v2.py        # v2 搜索爬虫
├── test_v1_api.py                  # API 诊断工具
├── sql/schema.sql                  # 建表脚本 (6 张表)
├── result/                         # v1 接口原始抓包数据
├── .aidocs/                        # 项目文档与逆向分析
│   ├── project-guide.md            #   完整项目文档
│   ├── troubleshooting-record.md   #   排障记录 (6 个核心问题)
│   └── reverse-engineering-review.md # JS 逆向分析报告
└── output/                         # JSON 输出目录
```

---

## 数据库

6 张表: `articles` → `article_authors` (1:N), `article_keywords` (1:N), `article_thesis_info` (1:0..1 学位论文), `articles_audit_log` (去重审计), `spider_run_log` (运行日志)

详细表结构见 [sql/schema.sql](sql/schema.sql)，设计文档见 [.aidocs/project-guide.md](.aidocs/project-guide.md)。

### 测试环境 (数据库隔离)

```bash
# 初始化测试库 academicdb_test (与业务库完全隔离, 结构相同)
python init_test_db.py

# 切换到 test 模式后运行 (推荐)
python env.py switch test
scrapy crawl pubscholar_v1

# 单次临时覆盖 (不改 .env, 数据/日志目录自动跟随库名):
$env:MYSQL_DATABASE="academicdb_test"                    # PowerShell 环境变量
scrapy crawl pubscholar_v1 -s MYSQL_DATABASE=academicdb_test   # Scrapy 单次

# 重置测试库 (清空测试数据)
python init_test_db.py --reset
```

---

## 技术要点

- **签名算法**: `SHA1(sorted([secret, timestamp, nonce]).join(""))`
- **密钥**: 从 JS 逆向提取，不包含 `/app/` 的接口使用 `6m6pingbinwaktg227gngifoocrfbo95`
- **设备指纹**: `x-finger` 是 MD5 格式的浏览器指纹，独立于签名，整个会话保持一致
- **同源检测**: 服务端通过 `Sec-Fetch-Site` 头判断请求来源，必须设为 `same-origin`
- **CSRF**: 需 `XSRF-TOKEN` Cookie + `X-XSRF-TOKEN` Header

完整逆向分析见 [.aidocs/reverse-engineering-review.md](.aidocs/reverse-engineering-review.md)。

---

## 注意事项

- **Windows 用户**: 建议直接使用 Scrapy 爬虫 (已内置 `spider_opened` 信号注入, 绕过 Windows 上 start_requests 不被调用的兼容性问题)
- **Cookie 过期**: API 返回 403 `"第三方应用独立请求时，无此操作权限"` 时需重新获取 Cookie
- **全量爬取时间**: ~7400 万条，1.5s/页，50 条/页，单线程约 140 天。建议多机部署
- **存储**: 全量数据预估 ~400GB，建议预留 600GB+
- **日志**: 文件日志按模式分流 —— prod→`logs/`、dev→`logs/dev/`、test→`logs/test/`，单文件 50MB 轮转保留 10 份。切换方式见上方「开发 vs 生产环境」。
