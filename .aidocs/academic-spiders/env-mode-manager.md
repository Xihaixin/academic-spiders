# 三模式配置管理 (env.py + EnvManager) 设计与实现记录

**日期**: 2026-09-02 | **版本**: v3.5
**关联**: [project-guide.md](../project-guide.md) §3.6 / §5.6

---

## 1. 背景与问题

此前开发/生产环境切换靠**手工复制粘贴** `.env` 配置块（源文件 `.local.env` 堆了三份内容），
存在三大痛点：

1. **易错**: 手工粘贴易漏键/粘贴错块，且无法直观看到当前处于哪个模式；
2. **不隔离**: 旧的日志分流只分 test (`logs/test/`) 与 "非 academicdb" (`logs/`) 两档，
   `academicdb`(现 dev) 与远程 `pubscholar`(现 prod) 语义冲突；
3. **零管理**: 无 Profile 仓库、无校验、无备份。

## 2. 目标

1. 一行命令在 test/dev/prod 三模式间切换，重写 `.env` 即生效（`settings.py` 逻辑零改动）；
2. 日志 + JSON 输出目录三模式各自独立；
3. 含真实密钥的 Profile 仓库 gitignored，模板可提交，团队可复制。

## 3. 设计决策（已与需求方确认）

| 决策点 | 结论 |
|--------|------|
| 接口形式 | `EnvManager` 类（`utils/env_manager.py`）+ 根目录 `env.py` CLI |
| Profile 存储 | `.env.profiles` 段式仓库，切换时重写 `.env` |
| 模式映射 | `test`=academicdb_test@localhost、`dev`=academicdb@localhost、`prod`=pubscholar@远程 |
| 日志目录 | prod→`logs/`、dev→`logs/dev/`、test→`logs/test/` |

## 4. 实现

### 4.1 文件清单

| 文件 | 说明 |
|------|------|
| `academic_spiders/utils/env_manager.py` | `EnvManager` 类 (读 profile / 反推当前模式 / 原子重写 .env) |
| `env.py` | CLI: `list` / `current` / `switch <mode>` / `init` |
| `.env.profiles` | Profile 仓库（gitignored，含真实密钥） |
| `.env.profiles.example` | 可提交模板（占位符） |
| `academic_spiders/utils/logging_config.py` | 三模式日志目录分流 (`resolve_mode`/`mode_of_db`/`log_subdir`) |
| `academic_spiders/pipelines.py` | `JsonExportPipeline` 输出目录改为按模式分流 |

### 4.2 EnvManager 关键流程 (switch)

```
get_profile(mode)                        # 从 .env.profiles 读取 [mode] 块
collect_extra()                          # .env 中不属于任何 profile 的键 (保留)
render(mode)                             # profile 键 + 自定义键 组装文本
write_env(mode):                         # 原子写: mkstemp → os.replace
  ├─ 备份原 .env → .env.bak
  └─ 写入新 .env (含 ACADEMIC_MODE=<mode> 标记)
```

### 4.3 模式解析规则 (logging_config)

```
resolve_mode():
  1. 实际生效 MYSQL_DATABASE → pubscholar=prod / academicdb=dev / 其他=test
  2. ACADEMIC_MODE 标记兜底
  3. 缺省默认 test (安全侧)

日志目录:  prod → PROJECT_ROOT/logs/
          dev  → PROJECT_ROOT/logs/dev/
          test → PROJECT_ROOT/logs/test/
```

**要点**: 库名优先于 `ACADEMIC_MODE` 标记，这样 `-s MYSQL_DATABASE=...`、launch.json env、
`--db-name` 等"只改数据层"的场景，日志目录也能跟随实际写入的库。

### 4.4 JSON 输出目录同步分流 (JsonExportPipeline)

由 `from_crawler` 按 `MYSQL_DATABASE` 解析模式后追加子目录：
`prod→output/`、`dev→output/dev/`、`test→output/test/`。

## 5. 使用示例

```bash
python env.py list                 # 列出三模式 + 当前生效 (◀)
python env.py current              # 查看 .env (密码脱敏)
python env.py switch test          # 本地测试
python env.py switch dev --dry-run # 预览
python env.py switch prod -y       # 远程生产 (二次确认)
python env.py init                 # 从 example 初始化 .env.profiles
```

## 6. 验证记录

| 验证项 | 结果 |
|--------|------|
| `env.py list` 识别当前 test | ✅ |
| 三种模式实际 switch 回环 (test→dev→prod→test) | ✅ |
| .env 生成 + .env.bak 备份 | ✅ |
| 自定义键 (MY_CUSTOM_KEY) 切换后保留 | ✅ |
| detect_active_mode: ACADEMIC_MODE 标记优先 → 库名兜底 | ✅ |
| 日志目录: pubscholar→logs/、academicdb→logs/dev、academicdb_test→logs/test | ✅ |
| shell 环境变量覆盖场景日志目录跟随库名 | ✅ |
| `from academic_spiders import settings` 正常导入 | ✅ |
| 各文件 `python -m compileall` 通过 | ✅ |

## 7. 使用注意

1. **密钥安全**: `.env.profiles` 已 gitignored，新增密钥键时勿复制进 `.env.profiles.example`；
2. **launch.json**: 调试配置里的 `env.MYSQL_*` 优先级高于 `.env`，若希望调试跟随 env.py 切换，
   删掉配置中 MYSQL_* 字段，先 `python env.py switch <mode>` 再 F5；
3. **跨机器**: clone 后先 `python env.py init` 生成 `.env.profiles` 再填密钥；
4. **`.local.env`**: 为历史手抄备份文件，已被 `.env.profiles` 取代，确认无需后手动删除即可。
