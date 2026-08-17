# 公益学术平台(scholarin.cn) 爬虫逆向工程完整复盘

> 从零到一，完整记录一个学术网站 API 反爬机制的逆向分析、破解与工程化过程。

---

## 目录

- [第一部分：加密逻辑的逆向分析方法论](#第一部分加密逻辑的逆向分析方法论)
  - [1.1 信息收集：从浏览器 DevTools 开始](#11-信息收集从浏览器-devtools-开始)
  - [1.2 定位加密入口：从 HTTP 请求头反向追踪](#12-定位加密入口从-http-请求头反向追踪)
  - [1.3 下载 JS 源码：精准捞取关键文件](#13-下载-js-源码精准捞取关键文件)
  - [1.4 代码定位策略：在压缩代码中大海捞针](#14-代码定位策略在压缩代码中大海捞针)
  - [1.5 密钥提取：追踪变量引用链](#15-密钥提取追踪变量引用链)
  - [1.6 算法验证：用已知数据反推确认](#16-算法验证用已知数据反推确认)
  - [1.7 方法论总结：可复用的逆向分析流程](#17-方法论总结可复用的逆向分析流程)
- [第二部分：工程实现中的问题与解决方案](#第二部分工程实现中的问题与解决方案)
  - [2.1 问题一：签名正确但 API 返回 403](#21-问题一签名正确但-api-返回-403)
  - [2.2 问题二：403 错误码的根因定位](#22-问题二403-错误码的根因定位)
  - [2.3 问题三：Sec-Fetch 头的发现与验证](#23-问题三sec-fetch-头的发现与验证)
  - [2.4 问题四：响应数据字段映射错误](#24-问题四响应数据字段映射错误)
  - [2.5 问题五：分页逻辑的差异](#25-问题五分页逻辑的差异)
  - [2.6 问题六：代理与网络环境兼容](#26-问题六代理与网络环境兼容)
  - [2.7 问题七：请求头完整性的重要性](#27-问题七请求头完整性的重要性)
- [第三部分：后续优化方向](#第三部分后续优化方向)
  - [3.1 Cookie 自动续期机制](#31-cookie-自动续期机制)
  - [3.2 多数据源扩展](#32-多数据源扩展)
  - [3.3 反爬对抗升级](#33-反爬对抗升级)
  - [3.4 性能优化](#34-性能优化)
  - [3.5 数据质量增强](#35-数据质量增强)
  - [3.6 工程化改进](#36-工程化改进)

---

# 第一部分：加密逻辑的逆向分析方法论

## 1.1 信息收集：从浏览器 DevTools 开始

一切逆向工程的起点都是**抓包**。用户在调试过程中已经发现了关键信息：

```
请求 URL: https://scholarin.cn/hky/api/v2/resources/article
请求方法: POST
```

请求头中有三个可疑的自定义字段：

```
nonce: 9G3SBX
timestamp: 1785942218109
signature: 4eef1a41b168459723ec236fded8b1d5f3a9a2f3
x-finger: 4eef1a41b168459723ec236fded8b1d5f3a9a2f3
```

**方法论要点：**

> 拿到一个目标网站后，第一件事不是看页面，而是打开 DevTools → Network 标签，触发目标操作（搜索、翻页等），观察 XHR/Fetch 请求。重点关注：
>
> 1. **请求头中的自定义字段**（如 `x-*`, `signature`, `nonce`, `token`）
> 2. **请求体中的加密字段**（如 `encrypted`, `sign`, `hash`）
> 3. **URL 参数中的动态字段**（如 `?_sign=xxx&_t=xxx`）
> 4. **Cookie 中的 token 类字段**（如 `XSRF-TOKEN`、`csrf_token`）
>
> 这些字段的共同特征：看起来随机、每次请求都不同、长度固定（暗示某种 hash 算法）。

### 初步推断

从已有信息可以做出以下假设：

| 字段 | 值示例 | 特征 | 假设 |
|------|--------|------|------|
| `nonce` | `9G3SBX` | 6 位大写字母+数字 | 随机字符串 |
| `timestamp` | `1785942218109` | 13 位数字 | JavaScript 毫秒时间戳 |
| `signature` | `4eef1a41b168459723ec236fded8b1d5f3a9a2f3` | 40 位十六进制 | **SHA-1** 哈希 |
| `x-finger` | 同 signature | 40 位十六进制 | 与 signature 相同值 |

**关键推断逻辑：**

- `signature` 是 40 字符的 hex 字符串 → 最常见的是 **SHA-1**（160 bits = 40 hex chars）
- `timestamp` 是 13 位 → `new Date().getTime()` 的典型输出（毫秒级 Unix 时间戳）
- `nonce` 是 6 位大写字母数字 → 可能是 `Math.random().toString(36).toUpperCase()`
- `signature` 和 `x-finger` 值相同 → 可能是同一个值用了两个头名

## 1.2 定位加密入口：从 HTTP 请求头反向追踪

下一步是最关键的：**找到生成这些请求头的 JavaScript 代码**。

### 策略：搜索请求头字段名

网站的前端代码中，设置请求头的代码必然包含字段名字符串。所以：

```
在 JS 文件中搜索: "signature", "nonce", "timestamp", "x-finger"
```

### 实际操作

```bash
# 下载首页和 JS 文件
curl https://scholarin.cn/explore -o page.html

# 从 HTML 中提取 JS 文件 URL
grep -oP 'src="[^"]+\.js"' page.html
# 结果:
# /static/js/manifest.3122638566cec9cfa621.js
# /static/js/vendor.1f4dfc18171e7277e59d.js
# /static/js/app.6a42b5832d7f2a058f2f.js

# 下载主逻辑 JS
curl https://scholarin.cn/static/js/app.6a42b5832d7f2a058f2f.js -o app.js
```

**方法论要点：**

> JS 文件通常分三类：
>
> 1. **manifest** — Webpack 运行时，通常很小（< 5KB），不含业务逻辑
> 2. **vendor** — 第三方库打包（如 Vue、axios、lodash），体积最大，**SHA1 等加密库在这里**
> 3. **app** — 业务代码，**加密调用逻辑在这里**
>
> 优先分析 app.js，如果找不到具体实现再到 vendor.js 中找。

## 1.3 下载 JS 源码：精准捞取关键文件

文件大小分析：

```
manifest.js  →  1.56 KB   (Webpack 运行时，跳过)
vendor.js    →  2.2 MB    (第三方库：SHA1、axios 等)
app.js       →  1.8 MB    (业务逻辑：API 调用、签名生成)
```

这三个文件都是 **Webpack 打包后的压缩代码**，没有任何换行，整个文件就是一行。直接阅读是不可能的，必须用**关键词搜索 + 上下文提取**的策略。

**方法论要点：**

> 面对压缩后的 JS，不要想着"读"代码，而要"搜"代码。核心技能是：
>
> 1. **选对搜索词** — 用你从抓包中看到的字段名去搜
> 2. **控制搜索粒度** — 第一次大范围搜，确认命中位置；第二次缩小范围，提取上下文
> 3. **利用 Webpack 模块特征** — `"moduleId":function(e,t,i){...}` 是模块边界

## 1.4 代码定位策略：在压缩代码中大海捞针

### 第一步：搜索 API 端点

先搜 `/api/v2/resources/article` 来找发起请求的代码。但实际搜索时发现端点字符串是拼凑的：

```javascript
// 不是直接写死的，而是：
l.a.defaults.baseURL = a._54  // baseURL = "https://scholarin.cn/hky"
// 然后调用时传相对路径 "/api/v2/resources/article"
```

### 第二步：搜索请求头字段名

在 app.js 中搜索 `signature`, `nonce`, `timestamp`，命中了一个关键片段：

```javascript
l.a.interceptors.request.use(function(e){
    var t=Object(r.k)(6),                    // nonce: 6位随机字符串
        i=(new Date).getTime().toString(),    // timestamp: 毫秒时间戳
        n=m()([a._16,i,t].sort().join(""));  // signature: hash 计算
    return e.headers.nonce=t,
           e.headers.timestamp=i,
           e.headers.signature=n,
           e.headers["x-finger"]=n,
           e
})
```

这就是**加密逻辑的核心**。

**方法论要点：**

> 这个发现是关键转折点。这段代码位于 **axios 拦截器**（`interceptors.request.use`）中，意味着：
>
> 1. **每次请求都会自动执行**这个函数
> 2. **所有 API 请求**共用同一套签名逻辑
> 3. 签名是在**请求发出前**动态生成的
>
> **关键经验：** 找加密逻辑时，优先搜索 HTTP 库的拦截器/中间件模式：
> - axios → 搜 `interceptors.request.use`
> - fetch → 搜 `fetch(` 附近的包装函数
> - XMLHttpRequest → 搜 `setRequestHeader`
> - jQuery → 搜 `$.ajaxSetup` 或 `beforeSend`

### 第三步：拆解算法

从上面一行代码中可以拆出完整的签名算法：

```
签名步骤:
1. nonce = random6Chars()                          # 6位随机大写字母数字
2. timestamp = new Date().getTime().toString()     # 毫秒时间戳转字符串
3. raw = [secret, timestamp, nonce].sort().join("")  # 三个值按字母序排序后拼接
4. signature = SHA1(raw)                           # 对拼接结果做 SHA1
```

### 第四步：追踪依赖链

代码引用了三个外部变量，需要分别定位：

```
a._16  →  密钥（secret key）
r.k    →  随机字符串生成器
m()    →  哈希函数（SHA1）
```

通过 Webpack 的模块声明找到对应的 import：

```javascript
var a=i("qI5z"),   // a = 配置模块（含 _16 密钥和 _54 baseURL）
    l=i("ZoQJ"),   // l = 工具函数模块（含 k 随机字符串生成器）
    h=i("uXeI"),   // h = SHA1 模块
    m=i.n(h);      // m = h 的默认导出 = SHA1 函数
```

## 1.5 密钥提取：追踪变量引用链

### 追踪 `a._16`

模块 `qI5z` 的导出声明中：

```javascript
i.d(t,"_16",function(){return Le})
```

所以 `_16` = 变量 `Le`。继续在 `qI5z` 模块中找到变量的赋值：

```javascript
Le="6m6pingbinwaktg227gngifoocrfbo95"
```

这就是签名密钥！32 位小写字母+数字。

### 追踪 `r.k`（随机字符串生成器）

模块 `ZoQJ` 中：

```javascript
i.d(t,"k",function(){return b})

// 变量 b 的定义：
b=function(e){
    if(!e)return null;
    for(var t="";t.length<e;t+=Math.random().toString(36).substr(2).toUpperCase());
    return t.substr(0,e)
}
```

Python 等价实现：

```python
import random, string

def generate_nonce(length=6):
    chars = []
    while len(chars) < length:
        rand_val = int(random.random() * 1e18)
        base36 = ""
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
        temp = rand_val
        while temp > 0 and len(base36) < 15:
            base36 = alphabet[temp % 36] + base36
            temp //= 36
        for ch in base36.upper():
            if ch.isalnum():
                chars.append(ch)
                if len(chars) >= length:
                    break
    return "".join(chars[:length])
```

简化版（效果等价）：

```python
import random, string

def generate_nonce(length=6):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))
```

### 追踪 `m()`（哈希函数）

模块 `uXeI` 是标准的 SHA-1 实现：

```javascript
// 关键参数：
a._blocksize=16
a._digestsize=20   // 20 bytes = 160 bits = SHA-1
```

输出格式：`bytesToHex` → 40 位十六进制字符串。

**方法论要点：**

> Webpack 模块的值追踪三板斧：
>
> 1. **找导出声明**：`i.d(t,"exportName",function(){return X})` → 导出名对应的变量是 `X`
> 2. **找变量赋值**：在模块顶部或中间找 `X="value"` 或 `X=function(){...}`
> 3. **验证明文值**：如果是字符串密钥，用你抓包的数据反推验证（见 1.6）
>
> 注意区分：Webpack 中 `i.d(t,name,fn)` 是定义导出，`var a=i("moduleId")` 是导入。

## 1.6 算法验证：用已知数据反推确认

这是整个逆向过程中**最重要的验证步骤**——在写代码之前，先用已知的正确数据验证你的推断。

已知数据（从用户提供的抓包记录）：

```
nonce = "9G3SBX"
timestamp = "1785942218109"
signature = "4eef1a41b168459723ec236fded8b1d5f3a9a2f3"
```

推断的密钥：

```
secret = "6m6pingbinwaktg227gngifoocrfbo95"
```

验证脚本：

```python
import hashlib

secret = "6m6pingbinwaktg227gngifoocrfbo95"
timestamp = "1785942218109"
nonce = "9G3SBX"

parts = sorted([secret, timestamp, nonce])
raw = "".join(parts)
print("Sorted parts:", parts)
# ['1785942218109', '6m6pingbinwaktg227gngifoocrfbo95', '9G3SBX']
print("Raw:", raw)
# 17859422181096m6pingbinwaktg227gngifoocrfbo959G3SBX

computed = hashlib.sha1(raw.encode()).hexdigest()
print("Computed:", computed)
# 4eef1a41b168459723ec236fded8b1d5f3a9a2f3
print("Expected:", "4eef1a41b168459723ec236fded8b1d5f3a9a2f3")
print("Match:", computed == "4eef1a41b168459723ec236fded8b1d5f3a9a2f3")
# Match: True ✅
```

**完全匹配！** 证明所有推断都是正确的。

**方法论要点：**

> **在写任何爬虫代码之前，先用已知数据验证算法。** 这是逆向工程中最重要的质量关卡。如果验证不通过：
>
> 1. 检查 `sort()` 的顺序 — 是数字排序还是字符串排序？（这里是**字符串排序**，因为 timestamp 和 nonce 都是字符串）
> 2. 检查字符串拼接是否有分隔符 — `join("")` 是无分隔符拼接
> 3. 检查是否遗漏了其他参数 — 有些算法会加 salt、前缀、后缀
> 4. 检查密钥是否正确 — 可能有多个密钥，对应不同端点
>
> 验证通过的好处：
> - 100% 确认算法正确，后续问题一定不是签名问题
> - 可以自信地排除"签名算错了"这个怀疑方向

## 1.7 方法论总结：可复用的逆向分析流程

```
┌─────────────────────────────────────────────────────────────┐
│               JS 反爬逆向分析通用流程                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 抓包                                                │
│  ├─ DevTools → Network → XHR/Fetch                          │
│  ├─ 触发目标操作（搜索/翻页/登录）                              │
│  └─ 标记所有可疑字段（加密参数、动态 header、token）             │
│                                                             │
│  Step 2: 推断                                                 │
│  ├─ 根据字段长度/格式推断算法类型                               │
│  │   ├─ 32 hex → MD5                                        │
│  │   ├─ 40 hex → SHA-1        ← 本项目                       │
│  │   ├─ 64 hex → SHA-256                                     │
│  │   └─ 128 hex → SHA-512                                    │
│  ├─ 推断时间戳精度（秒/毫秒）                                   │
│  └─ 推断随机串生成方式                                          │
│                                                             │
│  Step 3: 定位代码                                              │
│  ├─ 查看 HTML → <script src="..."> → 下载 JS                  │
│  ├─ 搜索请求头字段名（signature/nonce/timestamp）              │
│  ├─ 优先搜拦截器/中间件（interceptors/beforeSend）              │
│  └─ 提取加密函数的完整参数链                                    │
│                                                             │
│  Step 4: 提取密钥                                              │
│  ├─ 追踪导出变量 → 变量赋值                                     │
│  ├─ 区分 Webpack 模块边界（i.d / i("moduleId")）               │
│  └─ 记录所有硬编码字符串                                        │
│                                                             │
│  Step 5: 验证 ★★★（最重要的一步）                               │
│  ├─ 用抓包的真实数据（timestamp + nonce + 结果签名）做回测       │
│  ├─ Python/Node 复现算法                                       │
│  └─ 结果一致 → 正确 ✅ / 不一致 → 回到 Step 3                   │
│                                                             │
│  Step 6: 工程化                                                │
│  ├─ 封装为可复用的签名函数                                      │
│  ├─ 处理边界条件（过期、重试、限流）                              │
│  └─ 关注非加密因素（Cookie、Header、代理）                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 常见反爬类型速查

| 类型 | 特征 | 定位策略 |
|------|------|----------|
| 签名验证 | 请求头有 `sign`/`signature`/`token` | 搜索 `sign` + `interceptors` |
| 时间戳校验 | 有 `timestamp`/`_t`/`ts` 参数 | 结合签名一起搜索 |
| 随机数 | 有 `nonce`/`random`/`r` 参数 | 搜索 `Math.random` + 字段名 |
| AES 加密 | 请求体是 base64 乱码 | 搜索 `CryptoJS.AES`/`encrypt` |
| RSA 加密 | 有 `publicKey` 或超长密码串 | 搜索 `JSEncrypt`/`RSAKey` |
| 环境指纹 | 有 `fingerprint`/`deviceId` | 搜索 `canvas`/`navigator`/`screen` |
| WAF/Cookie | 返回 403/503 + 需要特定 Cookie | 先正常访问首页获取初始 Cookie |

---

# 第二部分：工程实现中的问题与解决方案

签名算法破解只是第一步。在实际请求 API 时，遇到了多个预期之外的问题。

## 2.1 问题一：签名正确但 API 返回 403

### 现象

```
Status: 403
Response: {"cause":"第三方应用独立请求时，无此操作权限","failure":true}
```

签名算法已用已知数据验证 100% 正确，但 API 仍然拒绝请求。

### 排查过程

**第一步：排除签名问题**

既然已知数据验证通过，签名本身不是问题。把怀疑方向转向**请求的其他部分**。

**第二步：区分认证级别**

系统性地测试各个 API 端点，看哪些需要认证：

| API 端点 | 结果 | 说明 |
|----------|------|------|
| `/api/v1/hot-search-keywords` | ✅ 200 | 公开接口 |
| `/api/v1/resources/article/suggestions` | ❌ 403 | 需要认证 |
| `/api/v2/resources/article` (POST) | ❌ 403 | 需要认证 |

这证明了一个事实：**文章相关的 API 需要认证**，而热搜关键词不需要。

**第三步：确定认证方式**

对比可用请求（浏览器）和不可用请求（Python）的区别：

| 项目 | 浏览器 | Python |
|------|--------|--------|
| Cookie | ✅ XSRF-TOKEN, hky_ticket, pub_ticket, JSESSIONID | ❌ 无 |
| UID | ✅ c9ca380e54f3455ca27bdeb6f921f7b0 | ❌ 无 |
| X-XSRF-TOKEN header | ✅ | ❌ 缺失 |

这就是 403 的原因——**缺少登录会话认证**。

### 解决方案

在爬虫中添加 Cookie 和 UID 支持：

```python
def __init__(self, cookies=None, uid=None, ...):
    # 1. 加载 Cookie 到 session
    if cookies:
        self._load_cookies(cookies)

    # 2. UID
    self._uid = uid or self.APP_ID

    # 3. 从 Cookie 自动提取 XSRF-TOKEN 用于请求头
    for cookie in self.session.cookies:
        if cookie.name == "XSRF-TOKEN":
            self._xsrf_token = cookie.value
```

## 2.2 问题二：加了 Cookie 还是 403

### 现象

给爬虫加了完整的 Cookie 和 UID 后，**仍然 403**。

### 排查过程

这很困惑——Cookie、UID、签名都正确，为什么还拒绝？

逐一对比浏览器请求和 Python 请求的**每一个**请求头：

```
浏览器有但 Python 缺少的关键头部：
  sec-ch-ua: "Not=A?Brand";v="99", "Microsoft Edge";v="151", "Chromium";v="151"
  sec-ch-ua-mobile: ?0
  sec-ch-ua-platform: "Windows"
  sec-fetch-dest: empty
  sec-fetch-mode: cors
  sec-fetch-site: same-origin    ← 关键！
```

## 2.3 问题三：Sec-Fetch 头的发现与验证

### 根因分析

`Sec-Fetch-Site: same-origin` 是浏览器自动添加的**安全头**（Forbidden Header），JavaScript 代码无法修改它。浏览器用这个头告诉服务器「这个请求来自同一个域名下的页面」。

服务器的 403 响应内容也暗示了这一点：

> "第三方应用独立请求时，无此操作权限"

「第三方应用独立请求」= 不是从 scholarin.cn 页面发起的请求 = `Sec-Fetch-Site` 不是 `same-origin`。

### 关键认知

- **浏览器中**：`Sec-Fetch-*` 头由浏览器自动添加，JS 无法修改
- **Python requests 中**：这些头可以**自由设置**，没有浏览器限制
- 服务器**仅靠这个头来判断**是否为同源请求

所以解决方案很简单：**在 requests 中手动添加这些浏览器才会发送的头**。

### 解决方案

```python
self.session.headers.update({
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
})
```

### 最小化验证

通过消融实验，确认最关键的头部：

```python
# 最少只需这 3 个关键头：
"X-XSRF-TOKEN": "bd371e5e-9f80-41e2-a11c-e1a122242703",
"Sec-Fetch-Site": "same-origin",
"Origin": "https://scholarin.cn",
```

加上它们后，403 消失了，成功返回 200 和数据。

**问题解决顺序总结：**

```
签名正确 + 无认证 = 403 "无此操作权限"
    ↓ 加 Cookie + UID
签名正确 + Cookie + UID - SecFetch = 403 "无此操作权限"
    ↓ 加 Sec-Fetch-Site: same-origin
签名正确 + Cookie + UID + SecFetch = 200 ✅ 但有数据解析问题
    ↓ 见 2.4
```

## 2.4 问题四：响应数据字段映射错误

### 现象

API 返回 200，但 `records` 始终为空：

```
Status: OK, code=N/A
总数: 0, 本页: 0 条
```

### 排查

打印实际响应的 JSON 结构：

```python
data = response.json()
print(data.keys())
# ['aggregation_map', 'content', 'totalElements', 'totalPages', 'size', ...]
```

原来的代码期望的路径是：

```python
records = data["data"]["records"]  # ❌ 不存在
total = data["data"]["total"]      # ❌ 不存在
```

实际的路径是：

```python
records = data["content"]          # ✅ 直接在最外层
total = data["totalElements"]      # ✅ 直接在最外层
```

### 解决方案

改为从实际路径提取，同时保留兼容性：

```python
@staticmethod
def _extract_pagination(data: dict) -> tuple:
    # v2 接口：content 直接在顶层
    if "content" in data:
        return (
            data.get("content") or [],
            data.get("totalElements") or 0,
            data.get("size") or 10,
        )
    # 兼容嵌套结构
    inner = data.get("data", data)
    records = inner.get("records") or inner.get("content") or []
    total = inner.get("totalElements") or inner.get("total") or 0
    return records, total, inner.get("size") or 10
```

**教训：**

> **永远不要假设 API 响应结构**。即使签名验证通过了、请求成功了，也要先 `print(json.dumps(response, indent=2)[:500])` 看一眼实际结构再写解析代码。

## 2.5 问题五：分页逻辑的差异

### 发现

API 的响应中分页字段名和常见的分页规范不同：

| 概念 | 常见命名 | 实际命名 |
|------|----------|----------|
| 当前页数据 | `records`, `items`, `data`, `list` | **`content`** |
| 总条数 | `total`, `count`, `totalCount` | **`totalElements`** |
| 总页数 | `totalPages`, `pageCount` | **`totalPages`** |
| 每页条数 | `pageSize`, `perPage` | **`size`** |
| 当前页码 | `page`, `current`, `pageIndex` | **`number`**（0-based） |

特别要注意 `number` 是 **0-based**（第1页 = 0，第3页 = 2），而请求参数 `page` 是 **1-based**（第1页 = 1）。

## 2.6 问题六：代理与网络环境兼容

### 现象

用户的网络环境需要通过代理 `127.0.0.1:7890` 访问目标网站，但 Python 环境中的代理配置混乱：

```
ProxyError: Cannot connect to proxy.
FileNotFoundError: No such file or directory
```

### 解决方案

添加灵活的代理配置：

```python
def __init__(self, proxy=None, no_proxy=False, ...):
    if no_proxy:
        self.session.trust_env = False  # 忽略系统代理环境变量
        self.proxies = None
    elif proxy:
        self.session.trust_env = False
        self.proxies = {"http": proxy, "https": proxy}
    else:
        self.proxies = None  # 使用系统环境变量
```

CLI 支持：

```bash
# 使用代理
--proxy http://127.0.0.1:7890

# 直连（忽略系统代理）
--no-proxy
```

## 2.7 问题七：请求头完整性的重要性

### 发现

在对 403 问题进行消融实验时，发现服务器的检查是**多因素组合**的 —— 单独加上某个头部可能不够，需要组合才能通过。

### 最终生效的完整请求头

```python
headers = {
    # === 签名相关（每次请求动态生成）===
    "nonce": nonce,           # 6位随机
    "timestamp": timestamp,   # 毫秒时间戳
    "signature": signature,   # SHA1 哈希
    "x-finger": signature,    # 同 signature

    # === 认证相关 ===
    "X-XSRF-TOKEN": xsrf_token,  # 从 Cookie 提取
    "Cookie": "XSRF-TOKEN=...; JSESSIONID=...",  # 登录会话

    # === 浏览器模拟 ===
    "Sec-Fetch-Site": "same-origin",  # 关键！标识同源请求
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Origin": "https://scholarin.cn",
    "User-Agent": "Mozilla/5.0 ... Edge/151.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
}
```

**教训：**

> 爬虫开发中的一大多因素问题：服务器反爬检查往往是**多层组合**的——签名、Cookie、浏览器头、请求频率，任何一个缺失都可能导致失败。当遇到 403 时，应该**逐项对齐**浏览器请求和 Python 请求的差异，而不是只关注签名的正确性。

---

# 第三部分：后续优化方向

## 3.1 Cookie 自动续期机制

### 当前问题

Cookie 是从浏览器手动复制的，有过期时间。一旦过期，爬虫就失效了。

### 优化方向

```python
class ScholarInSpider:
    def _auto_refresh_cookies(self):
        """
        通过模拟登录流程自动获取 Cookie
        可能的方案：
        1. 使用 playwright/selenium 打开登录页面
        2. 手动登录一次后，通过 refresh_token 续期
        3. 监控 API 响应中的 401，触发重新登录
        """
```

**具体方案：**

1. **方案 A：Refresh Token 机制**
   - 查找登录接口 `/oauth/authorize` 和 token 刷新接口
   - 用 `pub_ticket` 或 `hky_ticket` 换取新的 session
   - 优点：纯 HTTP 请求，不需要浏览器
   - 缺点：需要逆向登录流程

2. **方案 B：Playwright 自动化**
   - 使用 Playwright 打开浏览器，手动登录一次
   - 保存 `storage_state`（包含所有 Cookie）
   - 后续加载 state 文件恢复会话
   - 优点：不需要逆向登录接口
   - 缺点：依赖浏览器，速度较慢

3. **方案 C：Cookie 过期检测 + 通知**
   - 在请求失败时检查是否为 401/403
   - 自动切换到备用 Cookie 或通知用户更新
   - 优点：实现简单
   - 缺点：不够自动

## 3.2 多数据源扩展

### 当前状态

只实现了一个端点：`POST /api/v2/resources/article`

### 可扩展的端点

从前端代码中提取了完整 API 列表：

| 端点 | 功能 | 参数 |
|------|------|------|
| `/api/v1/resources/article/suggestions` | 搜索建议 | `?q=` |
| `/api/v2/resources/article` | 文章搜索 | POST `article_query` |
| `/api/v1/resources/project/suggestions` | 项目建议 | `?q=` |
| `/api/v1/resources/patent/suggestions` | 专利建议 | `?q=` |
| `/api/v1/resources/report/suggestions` | 报告建议 | `?q=` |
| `/api/v1/resources/journal/suggestions` | 期刊建议 | `?q=` |
| `/api/v1/resources/conference/suggestions` | 会议建议 | `?q=` |
| `/api/v1/resources/scholar/suggestions` | 学者建议 | `?q=` |
| `/api/v2/resources/project/suggestions` | 项目建议 v2 | `?q=` |
| `/api/v2/resources/monograph/suggestions` | 专著建议 | `?q=` |
| `/api/v2/resources/software/suggestions` | 软件建议 | `?q=` |
| `/api/v2/resources/award/suggestions` | 奖励建议 | `?q=` |
| `/api/v1/hot-search-keywords` | 热搜关键词 | 无 |

### 扩展架构

```python
class ScholarInSpider:
    # 当前
    def search_articles(self, query, page=1, ...): ...

    # 可添加
    def search_projects(self, query, page=1, ...): ...
    def search_patents(self, query, page=1, ...): ...
    def search_scholars(self, query, page=1, ...): ...
    def get_suggestions(self, query, resource_type="article"): ...
    def get_hot_keywords(self): ...
```

## 3.3 反爬对抗升级

### 当前网站可能升级的方向

1. **签名密钥轮换**
   - 密钥 `6m6pingbinwaktg227gngifoocrfbo95` 可能会在版本更新时变化
   - 对策：监控 JS 文件 hash 变化，自动提取新密钥

2. **增加请求频率限制**
   - 当前已有 429 处理，但阈值可能收紧
   - 对策：实现自适应延迟，被限流后自动加大间隔

3. **增加验证码**
   - 登录接口可能出现 CAPTCHA
   - 对策：接入打码平台或切换到 Cookie 方案

### 密钥自动更新方案

```python
class KeyManager:
    """监控 JS 文件变化，自动提取最新密钥"""

    JS_URL = "https://scholarin.cn/static/js/app.{hash}.js"

    def check_for_updates(self):
        # 1. 下载首页 HTML，提取最新 JS 文件 hash
        # 2. 与缓存的 hash 对比
        # 3. 如果变化，重新提取密钥
        # 4. 更新配置
```

## 3.4 性能优化

### 并发请求

当前是串行请求，每次间隔 1-2 秒。对于大量数据的场景，可以：

```python
import asyncio
import aiohttp

class AsyncScholarInSpider:
    async def search_batch(self, query, pages, concurrency=3):
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_page(page):
            async with semaphore:
                return await self._search_page(query, page)

        tasks = [fetch_page(p) for p in range(1, pages + 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
```

### 增量爬取

记录已爬取的 article_id，避免重复请求：

```python
class IncrementalSpider(ScholarInSpider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_ids = self._load_seen_ids()

    def _load_seen_ids(self):
        # 从 SQLite/Redis 加载已爬取的 ID 集合
        pass

    def search_new_only(self, query, ...):
        results = self.search_articles(query, ...)
        new_items = [r for r in results if r["id"] not in self.seen_ids]
        return new_items
```

## 3.5 数据质量增强

### 字段补全

当前提取的字段是 API 直接返回的。可以进一步增强：

```python
# 当前字段
extracted = {
    "title", "authors", "source", "pub_date", "doi",
    "abstract", "keywords", "article_type",
}

# 可添加的字段
enhanced = {
    # 从 API 已有但未提取的字段
    "attachments": "附件列表（PDF 文件名、大小、权限）",
    "institutions": "所有作者机构汇总",
    "corresponding_author": "通讯作者标识",
    "first_page": "起始页码",
    "impact_factor": "影响因子",

    # 需要二次计算/请求的字段
    "citation_detail": "引用详情",
    "related_articles": "相关论文推荐",
    "full_text_url": "全文下载链接",
}
```

### 数据清洗

```python
class DataCleaner:
    @staticmethod
    def clean_authors(author_str):
        """规范化作者格式：处理多余空格、分号分隔等"""
        pass

    @staticmethod
    def normalize_date(date_str):
        """统一日期格式：2026-03-12 / 2026-03 / 2026 → datetime.date"""
        pass

    @staticmethod
    def detect_language(text):
        """检测摘要语言，补充语种信息"""
        pass
```

## 3.6 工程化改进

### 配置管理

```python
# 从硬编码到配置文件
# config.yaml
scholarin:
  base_url: "https://scholarin.cn/hky"
  secret: ""  # 留空自动从 JS 提取
  endpoints:
    article_search: "/api/v2/resources/article"
    hot_keywords: "/api/v1/hot-search-keywords"
  request:
    timeout: 30
    max_retries: 3
    delay_min: 1.0
    delay_max: 2.0
  auth:
    cookies_file: "cookies.txt"
    uid: ""

# 使用时
config = yaml.safe_load(open("config.yaml"))
spider = ScholarInSpider.from_config(config["scholarin"])
```

### 日志与监控

```python
# 结构化日志
logger.info("search_completed", extra={
    "query": query,
    "pages": pages,
    "total_results": total,
    "duration_seconds": elapsed,
    "errors": error_count,
})

# 爬取状态持久化
class SpiderState:
    """保存爬取进度，支持断点续爬"""
    def save_checkpoint(self, query, last_page, collected_ids):
        pass

    def resume(self) -> Optional[Checkpoint]:
        pass
```

### 单元测试

```python
def test_signature_generation():
    """用已知数据验证签名算法"""
    spider = ScholarInSpider()
    ts = "1785942218109"
    nonce = "9G3SBX"
    sig = spider._generate_signature(ts, nonce)
    assert sig == "4eef1a41b168459723ec236fded8b1d5f3a9a2f3"

def test_nonce_format():
    """验证 nonce 格式：6 位大写字母数字"""
    spider = ScholarInSpider()
    for _ in range(100):
        n = spider._generate_nonce()
        assert len(n) == 6
        assert n.isalnum()
        assert n == n.upper()

def test_pagination_extraction_v2():
    """验证 v2 API 响应解析"""
    data = {
        "content": [{"id": "1"}, {"id": "2"}],
        "totalElements": 100,
        "size": 10,
    }
    records, total, size = ScholarInSpider._extract_pagination(data)
    assert len(records) == 2
    assert total == 100
    assert size == 10
```

---

## 第四部分：认证系统补充分析 (2026-08-07)

### 4.1 CSTCloud Passport 登录流程

pubscholar.cn 登录入口实际重定向到统一认证平台：

```
https://passport.escience.cn/login?returnUrl=https://pubscholar.cn/
```

登录机制为 CAS-like SSO + Spring Security：

1. GET 登录页面 → 提取 `_csrf` token（`<meta name="_csrf">`）
2. POST `/login`（username + password + _csrf）→ 302 重定向
3. 重定向回 pubscholar.cn → 服务端验证 ticket → 设置 `pub_ticket` + `XSRF-TOKEN` Cookie

`pub_ticket` 有效期约 **10 天**，无续期接口，过期必须重新登录。

### 4.2 Cookie 演进

| 阶段 | Cookie | 来源 | 生命周期 |
|------|--------|------|----------|
| 初始 (非登录) | `JSESSIONID` | 仅访问首页 | 数小时 |
| 登录后 | `pub_ticket` | passport.escience.cn SSO | ~10 天 |

当前项目完全基于 `pub_ticket` 登录态，支持通过 CSTCloud 账号密码自动登录（`check_cookies.py login`）。

### 4.3 v1/v2 接口行为变化

**观察 (2026-08-07)**: 登录后浏览器实际调用 v1 接口而非 v2。

推测：
- 站点将搜索功能统一迁移到 v1（v1 升级了登录认证支持）
- 或用户处于不同的 A/B 测试组
- scholarin.cn 域名下的 v2 需要该域名专属的 Cookie（`hky_ticket`）

当前项目以 v1 为主要目标，v2 Spider 暂缓。

---

## 附录

### A. 项目文件清单

```
academic-spiders/
├── scrapy.cfg, pyproject.toml
├── cookies.json, cookies.json.example
├── check_cookies.py
├── sql/schema.sql
├── academic_spiders/
│   ├── items.py, settings.py, middlewares.py, pipelines.py
│   ├── utils/signing.py, parsers.py, cookie_config.py, auth.py
│   └── spiders/pubscholar_v1.py, pubscholar_v2.py
├── run_v1_spider.py, run_v2_spider.py
├── test_v1_api.py
├── result/
├── .aidocs/
└── task.md
```

### B. 关键技术索引

| 技术点 | 文件 | 函数/位置 |
|--------|------|-----------|
| 签名算法 | `utils/signing.py` | `build_signature_headers()` |
| Nonce 生成 | `utils/signing.py` | `generate_nonce()` |
| 密钥常量 | `utils/cookie_config.py` | default dict |
| Cookie 检查 | `utils/auth.py` | `check_cookie_valid()` |
| 自动登录 | `utils/auth.py` | `auto_login()` |
| 字段解析 | `utils/parsers.py` | `record_to_item()` |
| 签名中间件 | `middlewares.py` | `PubscholarSigningMiddleware` |
| 过期检测 | `middlewares.py` | `PubscholarRetryMiddleware` |
| 数据管道 | `pipelines.py` | `MySQLPipeline`, `JsonExportPipeline` |

### C. 原始 JS 代码片段（已归档）

签名生成核心逻辑（来自 `app.js`，Webpack 模块 `whRD`）：

```javascript
var a = i("qI5z");   // 配置模块（密钥 _16、baseURL _54）
var r = i("ZoQJ");   // 工具模块（随机字符串 k）
var h = i("uXeI");   // SHA1 模块
var m = i.n(h);      // SHA1 默认导出

// 配置 baseURL
l.a.defaults.baseURL = a._54;

// 从 Cookie 提取 XSRF-TOKEN
var v = document.cookie.match(new RegExp("XSRF-TOKEN=([^;]+)"));
var f = null == v ? null : v[1];
f && (l.a.defaults.headers.common["X-XSRF-TOKEN"] = f);

// 请求拦截器：每次请求自动添加签名头
l.a.interceptors.request.use(function(e) {
    var t = Object(r.k)(6);                    // nonce: 随机6位
    var i = (new Date).getTime().toString();    // timestamp: 毫秒时间戳
    var n = m()([a._16, i, t].sort().join("")); // signature: SHA1
    return e.headers.nonce = t,
           e.headers.timestamp = i,
           e.headers.signature = n,
           e.headers["x-finger"] = n,
           e;
}, function(e) {
    return Promise.reject(e);
});
```
