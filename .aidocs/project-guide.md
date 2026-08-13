# 慧科研 (pubscholar.cn) 文献爬虫系统 — 项目文档

**版本**: 3.2 | **日期**: 2026-08-13

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

### 5.6 存储估算

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
