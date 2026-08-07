# 慧科研爬虫项目 — 错误分析与排障记录

**日期**: 2026-08-06

---

## 目录

1. [问题一：v1 API 返回 403"第三方应用独立请求时，无此操作权限"](#1)
2. [问题二：x-finger 字段误设为 signature 值](#2)
3. [问题三：Scrapy Windows reactor 不工作](#3)
4. [问题四：requests 库无法获取网站 Cookie](#4)
5. [问题五：ArticleItem _page 字段缺失](#5)
6. [问题六：数据库表结构迭代](#6)

---

## <a id="1"></a>问题一：v1 API 返回 403

### 现象

```json
{"cause":"第三方应用独立请求时，无此操作权限","failure":true}
```

v1 接口标注为"无需登录"，但直接 POST 请求返回 403。

### 尝试过程

**尝试 1**: 仅签名头 (nonce/timestamp/signature)
→ 403 ❌ 签名正确，但不是唯一条件

**尝试 2**: 签名头 + Origin
→ 403 ❌

**尝试 3**: 签名头 + Origin + Sec-Fetch 系列头
→ 403 ❌ `Sec-Fetch-Site: same-origin` 也不够

**尝试 4**: 访问 pubscholar.cn 首页获取 Cookie
→ Cookie 为空 ❌ 网站通过 JavaScript 设置 Cookie，requests 库无法执行 JS

**尝试 5**: 从用户浏览器获取真实 Cookie 后测试
```http
Cookie: XSRF-TOKEN=115318a2-...; JSESSIONID=ADE2864C...
X-XSRF-TOKEN: 115318a2-...
Sec-Fetch-Site: same-origin
```
→ 200 ✅

### 根因分析

"v1 无需登录"的含义是**不需要用户名/密码认证**，但服务器仍然检查：
1. **CSRF Token** (`XSRF-TOKEN` Cookie + `X-XSRF-TOKEN` Header) — 防止跨站请求
2. **同源标记** (`Sec-Fetch-Site: same-origin`) — 防止第三方应用直接调用
3. **会话标识** (`JSESSIONID`) — 追踪浏览会话

三者缺一不可。网站通过 JS 设置这些 Cookie（访问首页时），Python requests 库无法获取。

### 解决方案

从浏览器手动获取 Cookie 并配置到爬虫中：
- `V1_COOKIE` = 完整的 Cookie 字符串
- `V1_XSRF_TOKEN` = XSRF-TOKEN 的值

---

## <a id="2"></a>问题二：x-finger 字段误设为 signature 值

### 现象

原始 `scholarin_spider.py` 代码 (第 191 行)：
```python
"x-finger": signature,
```

我的初始代码也延续了这个错误：
```python
"x-finger": signature,
```

### 发现过程

对比两次浏览器抓包数据：

| 来源 | signature | x-finger |
|------|-----------|----------|
| `.aidocs` 文档 (4.2节) | `2696be6bb...` (变化) | `c84069ed...` (固定) |
| 用户实时抓包 | `4678a778...` (变化) | `c84069ed...` (固定) |

**关键发现**：`x-finger` 在两次不同时间的抓包中**完全一致**，而 `signature` 每次都不同。

### 根因分析

回看前端 JS 代码 (模块 `whRD`)：
```javascript
e.headers.signature = n;               // SHA1 签名 — 每次不同
e.headers["x-finger"] = Object(S.f)(); // 设备指纹 — 固定值
```

`Object(S.f)()` 是一个**设备指纹函数**（MD5 格式），与 SHA1 签名完全独立。x-finger 是浏览器端的设备标识，整个会话期间保持不变。

### 解决方案

1. 将 x-finger 从 `build_signature_headers()` 中分离
2. 设置为配置项 `V1_FINGER`，默认使用从浏览器捕获的固定值：
   ```python
   def build_signature_headers(secret: str, finger: str) -> dict:
       return {
           "nonce": nonce,
           "timestamp": timestamp,
           "signature": signature,      # SHA1 — 每次动态生成
           "x-finger": finger,          # 设备指纹 — 固定配置值
       }
   ```

---

## <a id="3"></a>问题三：Scrapy Spider 启动后瞬间关闭 (start_requests 不被调用 + CookiesMiddleware 冲突)

### 现象

执行 `scrapy crawl pubscholar_v1` 后，Spider 打开 → 瞬间关闭，0 请求发出：

```
16:18:22 [INFO] Spider opened
16:18:22 [INFO] Closing spider (finished)   ← 同一秒！
```

`start_requests()` 从未被调用，无任何错误日志，`elapsed_time_seconds: 0.0`。

### 根因分析 (2026-08-07 修正)

**原诊断 (v1.0) 是误判。** Scrapy 2.17 + Twisted 26.4.0 + Python 3.12 + Windows 11 **可以正常运行**（同环境下 `scrapy crawl quotes` 正常获取 110 条数据验证通过）。

真正的问题有 **两个独立 Bug**：

**Bug A: `start_requests()` 生成器不被 engine 调度**

在 Scrapy 2.17 + asyncio reactor + Windows 组合下，自定义 `start_requests()` 生成器方法无法被 engine 正确调度——`start_urls` 配合默认 `start_requests()` 正常，但任何 override 的生成器版本均不起效。这是 Scrapy 对 Twisted Deferred/生成器 与 Windows asyncio 事件循环交互的边界兼容问题。

验证方法：`CrawlerProcess` + `start_urls` 正常，`CrawlerProcess` + 自定义 `start_requests()` 静默失败。

**Bug B: `CookiesMiddleware` 清除我们注入的 Cookie header**

`PubscholarSigningMiddleware` 通过 `request.headers["Cookie"] = "XSRF-TOKEN=...; JSESSIONID=..."` 注入 Cookie，但 Scrapy 内置的 `CookiesMiddleware`（优先级 700，晚于签名中间件的 543）在 `process_request` 中执行：

```python
request.headers.pop('Cookie', None)  # 移除我们设置的 Cookie!
jar.add_cookie_header(request)       # 从 (空的) cookie jar 重新设置
```

由于 cookie jar 为空，最终请求**没有 Cookie**，API 返回 403 `"第三方应用独立请求时，无此操作权限"`。

### 解决方案 (已实施)

**Bug A 修复**: 在两个 Spider 中移除 `start_requests()` 方法，改用 `spider_opened` 信号 + `self.crawler.engine.crawl(request)` 注入初始请求：

```python
# pubscholar_v1.py / pubscholar_v2.py
from scrapy import signals

@classmethod
def from_crawler(cls, crawler, *args, **kwargs):
    spider = super().from_crawler(crawler, *args, **kwargs)
    crawler.signals.connect(spider._on_spider_opened, signal=signals.spider_opened)
    return spider

def _on_spider_opened(self):
    self.crawler.engine.crawl(self._build_page_request(self.start_page))
```

**Bug B 修复**: `settings.py` 中设置 `COOKIES_ENABLED = False`，因为签名中间件自行通过 header 注入管理所有 Cookie，无需 Scrapy 的 cookie jar 参与。

### 验证结果

```
v1 spider (scrapy crawl pubscholar_v1):
  3 页 × 50 条 = 150 items ✓
  总数据量: 74,374,920 条中文文献 / 1,487,499 页
  JSON 输出: output/page_000001.json ~ page_000003.json
```

---

## <a id="4"></a>问题四：requests 库无法获取网站 Cookie

### 现象

访问 `https://pubscholar.cn/` 和 `https://scholarin.cn/` 后，`session.cookies` 为空。

### 诊断

```python
session = requests.Session()
r = session.get("https://pubscholar.cn/")
print(list(session.cookies))  # → []
r = session.get("https://pubscholar.cn/explore")
print(list(session.cookies))  # → []
```

同样方法对 `scholarin.cn` 也返回空 Cookie 列表。

### 根因

这些网站通过 **JavaScript** 设置 Cookie（`document.cookie = "XSRF-TOKEN=..."`），而非通过 HTTP `Set-Cookie` 响应头。Python `requests` 库不执行 JavaScript。

### 解决方案

从浏览器 DevTools (F12 → Application → Cookies) 手动获取 Cookie 值，配置为项目设置。

---

## <a id="5"></a>问题五：ArticleItem _page 字段缺失

### 现象

```
KeyError: 'ArticleItem does not support field: _page'
```

### 原因

`run_v1_spider.py` 的 `_record_to_item()` 方法中设置了 `_page=page`，但 `ArticleItem` 类定义中没有声明 `_page` 字段。Scrapy Item 不允许设置未声明的字段。

### 解决方案

在 `ArticleItem` 类中添加 `_page = scrapy.Field()`，作为内部元数据字段。

---

## <a id="6"></a>问题六：数据库表结构迭代

### 迭代过程

**v1.0** (初始方案):
- `articles` 表: 32 个字段，VARCHAR(32) 主键，包含 extend_entity / semantic_entities JSON
- 6 张表: articles + article_authors + article_keywords + article_links + spider_run_log

**用户反馈**:
1. 去除 `browse_count`
2. 新增 `lang` 字段标识语种
3. 删除 `abstracts_abbr` (可由 abstracts 截取)
4. articles 表字段太多，应只保留核心信息
5. 学位论文字段移到其他表
6. extend_entity / semantic_entities 移到独立表
7. 确认 `id` 来源 (响应数据的 id) 和是否需自增主键

**v2.0** (修订版):
- `articles` 表: BIGINT 自增主键 + article_md5 UNIQUE KEY
- 精简到 16 个核心字段
- 新增 `article_extended_data` 表 (1:1)
- 新增 `article_thesis_info` 表 (1:0..1, 仅学位论文)
- 删除 `article_links` 表 → links JSON 并入 articles
- 删除 `author_inner_id`
- 所有子表添加 article_id(BIGINT) + article_md5(VARCHAR) 双关联

### 关键设计决策

| 决策 | 理由 |
|------|------|
| BIGINT 自增 PK 替代 VARCHAR(32) PK | InnoDB 聚簇索引: 顺序写入性能, 二级索引存储节省 |
| article_md5 作为 UNIQUE KEY 而非 PK | 保留平台 ID 唯一约束，但不做聚簇索引 |
| extend_entity 独立建表 | articles 精简; 低频查询不扫描大字段 |
| links 并入 articles (JSON) | 1-2 条/文, 无聚合查询需求, 减少 JOIN |
| 子表冗余 article_md5 | Pipeline 中直接用响应 id 查询，无需 JOIN articles |

---

## <a id="7"></a>问题七：v1/v2 接口行为变化观察 (2026-08-07)

### 现象

先前调试时，登录后浏览器使用 v2 接口 (`/hky/api/v2/resources/article`)。但今天重新登录后，浏览器实际请求的是 v1 接口 (`/hky/open/resources/api/v1/articles`)。

### 对比

| 维度 | 旧观察 | 新观察 |
|------|--------|--------|
| API 端点 | `/hky/api/v2/resources/article` (登录) | `/hky/open/resources/api/v1/articles` (登录) |
| Cookie | `JSESSIONID=...` (未登录) | `pub_ticket=...` (登录) |
| 域名 | `scholarin.cn` | `pubscholar.cn` |
| 鉴权方式 | 签名 + XSRF-TOKEN + JSESSIONID | 签名 + XSRF-TOKEN + pub_ticket |

### 推测原因

1. **站点前端更新**: 网站可能将搜索功能统一迁移到 v1 接口，v1 已升级为支持登录认证 (`pub_ticket`)。v2 接口可能仅在某些特定条件下使用（如特定搜索类型）。
2. **A/B 分流**: 用户可能处于不同的 A/B 测试组，不同组使用不同接口。
3. **Cookie 机制变更**: 旧版使用 `JSESSIONID`（未登录会话），新版使用 `pub_ticket`（登录票据），网站的认证体系做了升级。
4. **域名差异**: `scholarin.cn` 上的 v2 需要该域名专属的 Cookie（如 `hky_ticket`），而 `pubscholar.cn` 上的 v1 使用 `pub_ticket`。两个域名可能使用不同的认证 Cookie。

### 结论

- v1 接口经过升级后功能完备（支持登录认证），足够满足全量爬取需求
- v2 Spider 验证（M3）暂缓，待观测到 v2 接口实际被使用且有明确需求时再推进
- 当前项目以 v1 爬虫为主要工作目标
