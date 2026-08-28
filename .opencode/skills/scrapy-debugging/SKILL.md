---
name: scrapy-debugging
description: Scrapy 爬虫项目的运行与调试通用方法论。涉及 scrapy crawl 运行、测试库/生产库隔离、调试四件套、VSCode/breakpoint 断点调试、断点续爬、Windows 信号注入、中间件/管道/下载器延迟排查等场景时使用。
---

# scrapy-debugging

Scrapy 爬虫使用与调试的通用方法论。**通用流程为主，附带本项目（pubscholar 爬虫）示例**，可复制到其它 Scrapy 项目复用。

## 1. 运行方式

```bash
scrapy crawl <spider>                       # 运行
scrapy crawl <spider> -s KEY=VALUE          # 覆盖任意设置项
scrapy crawl <spider> -a arg=value          # 传入 spider 参数
scrapy crawl <spider> -L DEBUG              # 日志级别
```

- 依赖管理：项目常用 `uv`（`uv sync`），虚拟环境在 `.venv/`，用 `.venv/Scripts/python.exe` / `.venv/Scripts/scrapy.exe` 调用。
- 常用 `-s` 覆盖：`LOG_LEVEL`、`CONCURRENT_REQUESTS`、`DOWNLOAD_DELAY`、`AUTOTHROTTLE_ENABLED`、`MYSQL_DATABASE` 等。

## 2. 开发 / 生产环境隔离

- 原则：用**数据库名**区分环境，同一份代码不另维护两套。
  - 开发：`academicdb_test`（或任意非生产名），数据 + 日志自动隔离。
  - 生产：`academicdb`（默认）。
- 切换：环境变量 `MYSQL_DATABASE` 或 `-s MYSQL_DATABASE=academicdb_test`。
- 日志隔离：`logging_config.py` 按库名分流到 `logs/`（生产）与 `logs/test/`（开发）。
- 注意：Scrapy 的 `-s MYSQL_DATABASE` 只切数据层；要连日志一起隔离用环境变量或 runner 的 `--db-name`。

## 3. 调试四件套

| 保护 | 参数 | 作用 |
|------|------|------|
| 测试库 | `-s MYSQL_DATABASE=academicdb_test` | 数据不污染生产库 |
| 限制范围 | `-s V1_MAX_PAGES=3` / `-s V1_BUCKET_MAX_BUCKETS=2` | 快速出结果 |
| DEBUG 日志 | `-s LOG_LEVEL=DEBUG` | 看全链路细节 |
| 小页面 | `-s V1_PAGE_SIZE=3` | 响应小好分析 |

## 4. 断点调试

- **VSCode**：`launch.json` 预置配置，行号断点 → F5。
- **pdb**：代码内 `breakpoint()`，命令 `p` 打印 / `n` 下一行 / `s` 进入 / `c` 继续 / `q` 退出。
- **runner（同步 requests）**比 Scrapy 异步引擎断点体验好；Scrapy 断点调用栈更深，适合验证逻辑而非细调。

## 5. 常见坑与排查方向

| 现象 | 排查方向 |
|------|----------|
| Spider 打开即关闭、无请求 | Windows 下 `start_requests()` 生成器可能不被调度 → 用 `spider_opened` 信号 + `engine.crawl()` 注入初始请求 |
| Cookie 被清空 → 403 | `COOKIES_ENABLED=False`；由签名/认证中间件自行注入 Cookie header |
| 请求极慢 / 挂起 | 检查 `DOWNLOAD_DELAY` 语义（同域串行 + 延迟）；个别端点对特定客户端可能挂起 → 换 `requests` 直连验证 |
| 双重重试 | 自定义 RetryMiddleware 与内置 `RetryMiddleware` 都拦 403/429 → 分工：403 过期停止、429 限流重试，内置不再拦 403 |
| 数据写库失败 | 字段长度（如 `VARCHAR(10)` 存长日期）→ 解析器里截断；先看日志 `Data too long` 等 MySQL 报错 |
| JSON 输出互相覆盖 | 多模式/多桶共用页码 → 用全局递增序列号作为输出分组键 |

## 6. 断点续爬

- 基于运行日志表（如 `spider_run_log`）查上次 `last_page`，`resolve_start_page()` 取 last+1。
- 分桶模式（如聚合分桶）另有桶级状态表 `crawl_query_state` + 计划标记 `crawl_plan`，`query_hash` 幂等续爬。
- 参考本项目 `utils/resume.py`、`utils/query_state.py` 的实现思路。

## 7. 通用调试顺序

1. 先确认网络连通与认证（最小请求打接口）。
2. 用小页面/限页数跑通单次请求链路。
3. 再放开并发/延迟参数验证稳定性。
4. 最后验证数据落库与去重。

## 8. 跨项目复用

复制本 skill 到目标 Scrapy 项目即可；把示例中的爬虫名、配置项名替换为目标项目的即可。
