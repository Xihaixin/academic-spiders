# academic-spiders

慧科研 (pubscholar.cn / scholarin.cn) 学术文献数据采集系统。基于 Scrapy 框架，已破解 API SHA1 签名反爬机制，支持全量中文文献抓取和关键词检索。

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
# v1 — 全量获取中文文献 (无需登录)
python run_v1_spider.py -p 3 -s 10 --no-mysql   # 测试: 3 页, 不写库
python run_v1_spider.py --all -s 50             # 生产: 全量爬取

# v2 — 按关键词搜索 (需登录 Cookie)
python run_v2_spider.py -q "人工智能" --cookie "..." --xsrf-token "..." --uid "..."

# Linux/Mac 可直接用 Scrapy
scrapy crawl pubscholar_v1 -s V1_MAX_PAGES=10
scrapy crawl pubscholar_v2 -a query="人工智能"
```

---

## 两个接口

| | v1 (开放) | v2 (登录) |
|---|---|---|
| URL | `pubscholar.cn/hky/open/resources/api/v1/articles` | `scholarin.cn/hky/api/v2/resources/article` |
| 认证 | 无需登录，需会话 Cookie | 需登录 Cookie |
| 功能 | 全量中文文献 (~7400万) | 按关键词搜索 |
| 运行器 | `run_v1_spider.py` | `run_v2_spider.py` |

### 获取 Cookie

**v1** — 浏览器打开 https://pubscholar.cn/ (无需登录) → F12 → Application → Cookies → 复制 `XSRF-TOKEN` 和 `JSESSIONID`

**v2** — 浏览器登录 https://scholarin.cn/ → F12 → Network → 搜索一次 → 找到 API 请求 → 复制 Cookie / X-XSRF-TOKEN / uid

---

## 运行参数

### run_v1_spider.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-p, --pages` | 爬取页数 | 1 |
| `--all` | 爬取全部 | - |
| `-s, --page-size` | 每页条数 (最大 50) | 50 |
| `--start-page` | 断点续爬起始页 | 1 |
| `--cookie` | Cookie 字符串 | (预设) |
| `--xsrf-token` | XSRF Token | (预设) |
| `--min-delay` | 最小请求间隔 (秒) | 1.5 |
| `--max-delay` | 最大请求间隔 (秒) | 3.0 |
| `--no-mysql` | 禁用 MySQL 写入 | - |

### run_v2_spider.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-q, --query` | 搜索关键词 (**必填**) | - |
| `--cookie` | 登录 Cookie (**必填**) | - |
| `--xsrf-token` | XSRF Token (**必填**) | - |
| `--uid` | 用户 UID (**必填**) | - |

### 诊断工具

```bash
python test_v1_api.py   # 验证 API 连通性和签名
```

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
│       ├── pubscholar_v1.py        # v1 全量爬虫
│       └── pubscholar_v2.py        # v2 搜索爬虫
├── run_v1_spider.py                # Windows v1 运行器
├── run_v2_spider.py                # Windows v2 运行器
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

6 张表: `articles` → `article_extended_data` (1:1), `article_thesis_info` (1:0..1), `article_authors` (1:N), `article_keywords` (1:N), `spider_run_log`

详细表结构见 [sql/schema.sql](sql/schema.sql)，设计文档见 [.aidocs/project-guide.md](.aidocs/project-guide.md)。

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

- **Windows 用户**: Scrapy reactor 在 Win + Py3.12 下有兼容性问题，请使用 `run_v1_spider.py` / `run_v2_spider.py`
- **Cookie 过期**: API 返回 403 `"第三方应用独立请求时，无此操作权限"` 时需重新获取 Cookie
- **全量爬取时间**: ~7400 万条，1.5s/页，50 条/页，单线程约 140 天。建议多机部署
- **存储**: 全量数据预估 ~400GB，建议预留 600GB+
