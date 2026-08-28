# opencode Skills — AI 开发流程与文档沉淀

围绕 `.aidocs` 设计思想封装的可复用 opencode skill 项目，覆盖 AI 开发全流程（提示词 → AI 响应 → 确认 → 调整 → 反馈 → 沉淀文档），跨项目复用、减少重复提示词。

## 包含的 Skills

| Skill | 用途 | 触发场景 |
|-------|------|----------|
| `aidocs-workflow` | **核心**：AI 开发全流程纪律 + `.aidocs` 文档组织/沉淀规范 | 多步骤开发任务、要求记录过程、总结/复盘、初始化 `.aidocs` 结构 |
| `scrapy-debugging` | Scrapy 项目使用与调试通用方法论 | `scrapy crawl`、测试库隔离、调试四件套、断点、续爬、中间件/下载器排查 |
| `crawler-debugging` | API 爬虫调试（验证优先） | 接口连通/签名验证、请求头完整性、分页窗口探测、聚合分桶遍历、去重续爬 |

## .aidocs 设计思想

```
.aidocs/
├── *.md               # AI 生成的综合文档（根目录）
├── archive/           # 历史/存档信息（过时方案、已废弃决策）
└── <project-name>/    # 与项目同名，记录细节信息（单任务分析、设计、过程）
```

- 根目录综合文档由 AI 生成；`archive/` 与 `<项目名>/` 沉淀过程细节。
- 开发者可在 AI 文档基础上二次精选整理。
- 新文档必须交叉引用已有文档，避免信息孤岛。

## 跨项目复用

1. 复制本 `skills/` 目录到目标项目（`.opencode/skills/`），或安装到全局 `~/.config/opencode/skills/` 使所有项目自动可用。
2. 替换 skill 内"项目示例"为目标项目场景（爬虫名、配置项、接口）。
3. 用 `aidocs-workflow` 初始化目标项目 `.aidocs` 骨架。
4. 修改配置/新增 skill 后需**重启 opencode** 生效。
