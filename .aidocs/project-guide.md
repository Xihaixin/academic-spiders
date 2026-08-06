# 慧科研 (pubscholar.cn) 文献爬虫系统 — 项目文档

**版本**: 1.0 | **日期**: 2026-08-06

---

## 1. 项目概述

基于 Scrapy 框架构建的 pubscholar.cn/scholarin.cn 学术文献数据采集系统，覆盖两个 API 接口：

| 接口 | URL | 认证 | 数据量 |
|------|-----|------|--------|
| v1 (开放) | `POST /hky/open/resources/api/v1/articles` | 无需登录，需会话 Cookie | ~7400万中文文献 |
| v2 (登录) | `POST /hky/api/v2/resources/article` | 需登录 Cookie | 按关键词搜索 |

**核心技术点**：
- SHA1 签名反爬对抗 (逆向自前端 Webpack 打包代码)
- 设备指纹 (x-finger) 模拟
- 同源请求头 (Sec-Fetch-Site) 伪造
- CSRF Token (XSRF-TOKEN) 管理

---

## 2. 项目结构

```
academic-spiders/
├── scrapy.cfg                          # Scrapy 部署配置
├── pyproject.toml                      # uv 依赖管理
│
├── sql/
│   └── schema.sql                      # 数据库建表脚本 (6 张表)
│
├── academic_spiders/                   # Scrapy 项目包
│   ├── items.py                        # ArticleItem 数据模型
│   ├── settings.py                     # 全局配置
│   ├── middlewares.py                  # 签名 + Cookie 注入中间件
│   ├── pipelines.py                    # MySQL + JSON 双管道
│   ├── utils/
│   │   └── signing.py                  # 签名工具 (nonce/timestamp/SHA1/finger)
│   └── spiders/
│       ├── pubscholar_v1.py            # v1 全量爬虫
│       └── pubscholar_v2.py            # v2 搜索爬虫
│
├── run_v1_spider.py                    # Windows v1 运行器
├── run_v2_spider.py                    # Windows v2 运行器
├── test_v1_api.py                      # API 连通性诊断工具
│
├── result/                             # v1 接口抓包数据
├── .aidocs/                            # 项目文档与逆向分析
└── output/                             # JSON 输出目录
```

---

## 3. 运行方式

### 3.1 Windows (推荐)

Scrapy 的 Twisted reactor 在 Windows + Python 3.12 环境下存在兼容性问题 (详见 [troubleshooting-record.md](troubleshooting-record.md))，请使用专用运行器：

```bash
# v1 — 全量爬取中文文献
python run_v1_spider.py --all -s 50

# v1 — 测试 (3 页，不写 MySQL)
python run_v1_spider.py -p 3 -s 10 --no-mysql

# v1 — 断点续爬
python run_v1_spider.py --all --start-page 10000

# v2 — 关键词搜索 (需登录 Cookie)
python run_v2_spider.py -q "人工智能" --cookie "..." --xsrf-token "..." --uid "..."
```

### 3.2 Linux / Mac

```bash
# v1
scrapy crawl pubscholar_v1 -s V1_MAX_PAGES=10

# v2
scrapy crawl pubscholar_v2 -a query="人工智能"
```

### 3.3 API 诊断

```bash
python test_v1_api.py    # 验证 API 连通性和签名正确性
```

---

## 4. 配置说明

核心配置位于 `academic_spiders/settings.py`：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `PUBSCHOLAR_SECRET` | SHA1 签名密钥 | `6m6pingbinwaktg227gngifoocrfbo95` |
| `PUBSCHOLAR_USER_ID` | 请求中的 user_id | `0b68c43...` |
| `V1_COOKIE` | 会话 Cookie | 需定期更新 |
| `V1_XSRF_TOKEN` | CSRF Token | 需定期更新 |
| `V1_FINGER` | 设备指纹 | `c84069ed...` |
| `CONCURRENT_REQUESTS` | 并发数 | 8 |
| `DOWNLOAD_DELAY` | 请求间隔 (秒) | 1.5 |
| `AUTOTHROTTLE_ENABLED` | 自适应限速 | True |

---

## 5. 数据库

### 5.1 表结构

```
articles (1) ───── (1) article_extended_data
     │
     ├── (1) ───── (0..1) article_thesis_info   (仅学位论文)
     ├── (1) ───── (N) article_authors
     └── (1) ───── (N) article_keywords

spider_run_log
```

### 5.2 建表

```bash
mysql -u root -p academicdb < sql/schema.sql
```

### 5.3 存储估算

| 表 | 行数 | 大小 |
|----|------|------|
| articles | 7400万 | ~90GB |
| article_extended_data | 7400万 | ~60GB |
| article_authors | 6亿 | ~150GB |
| article_keywords | 5亿 | ~90GB |
| **合计** | | **~400GB** |

---

## 6. 签名算法

```
nonce     = random(6 chars, A-Z + 0-9)
timestamp = Date.now()  (13位毫秒)
signature = SHA1(sorted([secret, timestamp, nonce]).join(""))
x-finger  = MD5(device_fingerprint)  (独立于 signature!)
```

**密钥有两套**，按 URL 判断：

| URL 条件 | 密钥 |
|----------|------|
| 包含 `/app/` | `foocrg227gng6m6fbo95inwakpingbti` |
| 不包含 `/app/` | `6m6pingbinwaktg227gngifoocrfbo95` |

v1 和 v2 接口均不包含 `/app/`，使用同一密钥。

---

## 7. Cookie 获取方法

### v1 (pubscholar.cn)
1. 浏览器打开 `https://pubscholar.cn/` (无需登录)
2. F12 → Application → Cookies
3. 复制 `XSRF-TOKEN` 和 `JSESSIONID` 的值

### v2 (scholarin.cn)
1. 浏览器登录 `https://scholarin.cn/`
2. F12 → Network → 搜索任意关键词
3. 找到 `/hky/api/v2/resources/article` 请求
4. 复制 Cookie / X-XSRF-TOKEN / uid

### Cookie 过期处理
Cookie 过期后 API 返回 403 `"第三方应用独立请求时，无此操作权限"`。重新按上述步骤获取即可。

---

## 8. 运行参数参考

### run_v1_spider.py

| 参数 | 说明 | 默认 |
|------|------|------|
| `-p, --pages` | 爬取页数 | 1 |
| `--all` | 爬取全部 | - |
| `-s, --page-size` | 每页条数 (最大50) | 50 |
| `--start-page` | 起始页码 | 1 |
| `--cookie` | Cookie 字符串 | (预设值) |
| `--xsrf-token` | XSRF Token | (预设值) |
| `--min-delay` | 最小间隔 (秒) | 1.5 |
| `--max-delay` | 最大间隔 (秒) | 3.0 |
| `--no-mysql` | 禁用 MySQL | - |

### run_v2_spider.py

| 参数 | 说明 | 默认 |
|------|------|------|
| `-q, --query` | 搜索关键词 (必填) | - |
| `--cookie` | 登录 Cookie (必填) | - |
| `--xsrf-token` | XSRF Token (必填) | - |
| `--uid` | 用户 UID (必填) | - |
