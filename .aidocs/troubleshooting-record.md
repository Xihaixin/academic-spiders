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

## <a id="3"></a>问题三：Scrapy Windows reactor 不工作

### 现象

执行 `scrapy crawl pubscholar_v1` 后，Spider 打开 → 瞬间关闭，0 请求发出：

```
16:18:22 [INFO] Spider opened
16:18:22 [INFO] Closing spider (finished)   ← 同一秒！
```

`start_requests()` 从未被调用，无任何错误日志，`elapsed_time_seconds: 0.0`。

### 诊断过程

**Step 1**: 怀疑 spider 代码问题 → 添加 `print()` 和 `logger.info()` 到 `start_requests` 入口
→ 无输出，确认该方法**从未被调用** ❌

**Step 2**: 怀疑 spider `from_crawler` 初始化问题 → 直接实例化 spider 对象测试
```python
s = PubscholarV1Spider()
list(s.start_requests())  # → 1 个 Request 对象 ✅
```
→ Spider 代码本身正常 ✅

**Step 3**: 怀疑 settings/middleware/pipeline 问题 → 用 `runspider` + 最简蜘蛛 + 空配置
```python
class SimpleSpider(scrapy.Spider):
    name = "simple"
    def start_requests(self):
        yield scrapy.Request("https://httpbin.org/get", ...)
```
→ 同样的 "Spider opened → Closing spider (finished)" ❌

**Step 4**: 怀疑 Twisted 版本问题 → 尝试不同 reactor
- 默认 AsyncioSelectorReactor → ❌
- SelectReactor (`-s TWISTED_REACTOR=twisted.internet.selectreactor.SelectReactor`) → ❌
- 显式 `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` → ❌

全部失败。

**Step 5**: 验证请求本身能通 → 用 `requests` 库直接调用 API
```python
requests.post(url, json=payload, headers=headers)  # → 200 ✅
```
→ API、签名、Cookie 全部正常 ✅

### 根因分析

**环境**: Windows 11 + Python 3.12.12 + Scrapy 2.17.0 + Twisted 26.4.0

Scrapy 2.17 默认使用 `twisted.internet.asyncioreactor.AsyncioSelectorReactor`。在 Windows 上，该 reactor 的事件循环不会正确调度 Spider 的 `start_requests`。引擎调用 `spider.start_requests()` 后，返回的生成器被包装成 Twisted task，但 task 从未被 reactor 调度执行。reactor 认为无事可做，立即退出。

这是 Twisted + asyncio + Windows 平台的已知兼容性问题，Scrapy 官方推荐在 Windows 上使用 `CrawlerRunner` + 显式 `reactor.run()`，但同样不工作。

### 解决方案

**短期方案** (已实施)：创建独立运行器 `run_v1_spider.py` / `run_v2_spider.py`，使用 `requests` 库替代 Scrapy 引擎做 HTTP 请求，同时复用 Scrapy 的 Item 和 Pipeline 组件进行数据处理和存储。

```python
# 核心架构不变
from academic_spiders.items import ArticleItem
from academic_spiders.pipelines import MySQLPipeline
from academic_spiders.utils.signing import build_signature_headers

# 用 requests 替代 Scrapy engine
import requests
session.post(url, json=payload, headers=headers)
```

**长期方案** (环境层面):
- Linux/Mac 上直接使用 `scrapy crawl`
- 降级到 Scrapy 2.11 + Twisted < 24 的稳定组合
- 安装 `pywin32` 并尝试 `iocpreactor`

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
