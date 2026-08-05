# academic-spiders

慧科研 (scholarin.cn) 论文数据爬虫。已破解 API 签名反爬机制（SHA1 + nonce + timestamp）。

## 快速开始

```bash
# 1. 安装依赖
pip install requests

# 2. 运行（需要提供浏览器 Cookie 和 UID）
python scholarin_spider.py -q "人工智能" -p 3 \
    --cookies "你的Cookie字符串" \
    --uid "你的uid" \
    --extract
```

## 获取认证信息

1. 浏览器登录 https://scholarin.cn/explore
2. F12 → Network → 搜索任意关键词
3. 找到 `/hky/api/v2/resources/article` 请求
4. 复制 **Cookie** 值和请求体中的 **uid**

## 完整参数

| 参数 | 说明 |
|------|------|
| `-q, --query` | 搜索关键词（必填） |
| `-p, --pages` | 爬取页数（默认 1） |
| `--all` | 获取全部结果 |
| `--sort` | 排序: pub_date / relevance / citation |
| `--order` | 方向: desc / asc |
| `--format` | 输出格式: json / csv |
| `--extract` | 提取关键字段保存 |
| `--cookies` | Cookie 字符串 |
| `--cookies-file` | 从文件加载 Cookie |
| `--uid` | 用户 UID |
| `--proxy` | HTTP 代理 |
| `-v` | 详细日志 |

## 诊断工具

```bash
python diagnose_auth.py   # 交互式诊断 Cookie/UID 是否有效
```

## 技术细节

- **签名算法**: `SHA1(sorted([secret, timestamp, nonce]).join(""))`
- **密钥**: 从 JS 逆向提取 (`qI5z` 模块 `_16` 变量)
- **认证**: 需要登录后的 Cookie（XSRF-TOKEN + JSESSIONID）和 UID
- **Sec-Fetch**: 服务器检查 `Sec-Fetch-Site: same-origin` 来防跨站请求

