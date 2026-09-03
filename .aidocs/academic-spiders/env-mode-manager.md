# 三模式配置管理 (配置类 + 注册表) 设计与实现记录

**日期**: 2026-09-03 | **版本**: v3.5 (配置类重构版)
**关联**: [project-guide.md](../project-guide.md) §3.6 / §5.6

---

## 1. 背景与问题

最初模式切换靠手工复制 `.env` 块；第一版工具用 EnvManager "整块重写 .env"。
但整块重写仍属于"改环境变量键值"，存在三点不足：

1. **复杂**: .env 内容随模式整体替换, 与具体配置值的定义割裂;
2. **难扩展**: 新增一个模式 = 复制一份完整 env 块, 没有面向对象结构;
3. **不统一**: 日志目录/数据库/JSON 输出分散判断, 没有单一配置对象承载。

## 2. 目标 (配置类方案)

1. `ConfigBase` 定义模式共有结构; 每模式一个子类承载属性/值;
2. `.env` 退化为单一开关 `ACADEMIC_MODE=test|dev|prod`;
3. 注册表 (registry) 依据开关选择激活配置对象;
4. settings.py / 日志 / JSON 输出 / 数据库连接 全部由该配置对象派生;
5. 敏感字段 (密码、远程主机) 存 gitignored 的 `.env.secrets`, 代码可提交。

## 3. 架构

```
academic_spiders/config/
├── __init__.py         # 导出 get_active_config/get_active_mode/... 
├── base.py             # ConfigBase: 共有结构 + 派生路径 (log/json)
├── modes.py            # TestConfig / DevConfig / ProdConfig (非敏感值)
├── secrets.py          # .env.secrets 解析 (敏感字段)
└── registry.py         # MODE_CLASSES + 按 ACADEMIC_MODE 选配置
```

关键文件: `env.py` (CLI), `.env` (单开关), `.env.secrets` (密钥), `settings.py` (消费方)。

## 4. 数据流

```
env.py switch dev ──set_active_mode()──▶ .env: ACADEMIC_MODE=dev
                                           │ (scrapy 启动 load_dotenv)
                                           ▼
settings.py: _ACTIVE_CONFIG = get_active_config()
   │  读取 MODE_CLASSES["dev"]() + secrets (dev 密码)
   ▼
MYSQL_* / ACADEMIC_JSON_OUTPUT / 日志目录 ──▶ pipelines/extensions/query_state 等照旧
```

## 5. 模式 → 值对照 (默认, 敏感字段在 .env.secrets)

| 模式 | 类 | 数据库 | 主机 | 日志目录 | JSON 输出 | 密码源 |
|------|-----|--------|------|----------|-----------|--------|
| test | `TestConfig` | `academicdb_test` | localhost | `logs/test/` | `output/test/` | .env.secrets [test] |
| dev | `DevConfig` | `academicdb` | localhost | `logs/dev/` | `output/dev/` | .env.secrets [dev] |
| prod | `ProdConfig` | `pubscholar` | (secrets) | `logs/` | `output/` | .env.secrets [prod] |

非敏感字段直接写在子类 (可提交); `ProdConfig` 的 host/user/password 属敏感基础设施
信息, 默认空串, 由 `.env.secrets` 的 `[prod]` 段注入。

## 6. 文件清单

| 文件 | 说明 |
|------|------|
| `academic_spiders/config/base.py` | ConfigBase: mode/label、MYSQL_*、json_subdir、派生 log_dir/json_output_dir、is_test/is_dev/is_prod、环境变量二次覆盖 |
| `academic_spiders/config/modes.py` | 三个模式子类 (非敏感默认值) |
| `academic_spiders/config/secrets.py` | 解析 .env.secrets 指定模式段 |
| `academic_spiders/config/registry.py` | MODE_CLASSES 注册表; get_active_mode/get_active_config/set_active_mode/list_modes |
| `.env.secrets` | gitignored, 真实密钥 |
| `.env.secrets.example` | 可提交模板 (占位符) |
| `env.py` | list / current / switch (只写 ACADEMIC_MODE) / init |
| `.env` | 仅 `ACADEMIC_MODE` 开关 (+ 非模式键如 ACADEMIC_JSON_OUTPUT) |

## 7. 使用示例

```bash
python env.py list                      # 列出三模式 + 当前 (◀)
python env.py current                   # 查看激活配置 (脱敏)
python env.py switch test|dev|prod      # 切换 (只改 ACADEMIC_MODE)
python env.py switch prod               # 二次确认
python env.py init                      # 从 example 初始化 .env.secrets
scrapy crawl pubscholar_v1              # 自动使用激活模式配置
```

程序内切换: `set_active_mode("dev", persist=False)` (测试/脚本) 或修改 `ACADEMIC_MODE` 环境变量。

## 8. 兼容性设计

1. **环境变量二次覆盖**: ConfigBase 构造后若进程环境存在 `MYSQL_*`, 会覆盖类值
   (临时单次覆盖, 优先级: 环境变量 > secrets > 类默认);
2. **logging_config 缺省 dev**: 未设 ACADEMIC_MODE 且无 MYSQL_DATABASE 时回退 dev;
3. **-s MYSQL_DATABASE=... 仍可用**: Scrapy 单次数据层覆盖, 日志目录仍跟随激活模式。

## 9. 验证记录

| 验证项 | 结果 |
|--------|------|
| env.py list / current / switch 三模式回环 | ✅ |
| .env 只保留 ACADEMIC_MODE + 非模式键 | ✅ |
| secrets 注入 (test/dev/prod 密码、prod host) | ✅ |
| settings.py 读取与激活模式一致 | ✅ |
| 环境变量二次覆盖生效 | ✅ |
| 真实爬虫冒烟 (test, 限 1 桶) item 889 落 test 库/日志/UNC test 目录 | ✅ |
| dev/prod 输出目录不被 test 混入 | ✅ |
| compileall 通过 | ✅ |

## 10. 注意

1. **密钥安全**: `.env.secrets` 已 gitignored, 新增模式需同步加该文件段;
2. **launch.json**: `envFile: .env` 只提供 ACADEMIC_MODE, MYSQL_* 来自配置类;
3. **跨机器**: clone 后 `python env.py init` → 填 `.env.secrets` → `python env.py switch <mode>`;
4. **历史遗留**: 早期 `env_manager.py` / `.env.profiles` 已删除, 被 config 包取代。
