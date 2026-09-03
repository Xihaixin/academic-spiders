"""
配置系统基类 (ConfigBase)

设计目标: 以"配置类 + 注册表"取代"整块重写 .env"的模式切换方式。

三种模式共用:
  - ConfigBase:  定义所有模式共有的接口/默认值/派生路径 (日志目录/JSON 输出目录等)
  - 模式子类:    继承 ConfigBase, 各自定义非敏感属性与值 (见 modes.py)
  - secrets:     敏感字段 (密码等) 存于 gitignored 的 .env.secrets, 构造时合并
  - registry:    根据 .env 中单一开关 ACADEMIC_MODE 选择激活的配置对象

使用方 (settings.py) 通过 registry.get_active_config() 拿到当前配置对象,
将其属性写入 Scrapy Settings 的 MYSQL_* / 日志目录等; 现有组件继续读 settings。
"""

import os
from pathlib import Path
from typing import Optional

from academic_spiders.utils.logging_config import PROJECT_ROOT, log_subdir


class ConfigBase:
    """所有模式共有的基类"""

    # ── 模式标识 (子类覆盖) ─────────────────────────────────
    mode: str = ""                # test / dev / prod
    label: str = ""               # 中文说明

    # ── 数据库连接 (子类覆盖非敏感部分; 密码由 secrets 提供) ──
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_DATABASE: str = ""
    MYSQL_PASSWORD: str = ""       # 敏感, 默认空, 构造时从 secrets 填充

    # ── 输出/日志 (子类覆盖子目录) ──────────────────────────
    # logs/ 与 JSON 输出根目录下的子目录 (子类可覆盖; prod 为空串 = 根目录)
    json_subdir: str = ""

    # ── 派生配置 (构造后计算) ───────────────────────────────
    _json_base_dir: str = "./output"
    _env_file_override: Optional[str] = None   # 供单测/程序内覆盖 .env 路径

    def __init__(self, secrets: Optional[dict] = None):
        """用 secrets 覆盖敏感字段; 允许环境变量二次覆盖"""
        for key in ("MYSQL_PASSWORD", "MYSQL_HOST", "MYSQL_PORT",
                    "MYSQL_USER", "MYSQL_DATABASE"):
            if secrets and key in secrets and secrets[key]:
                setattr(self, key, secrets[key])
        self._apply_env_overrides()

    # ── 环境变量二次覆盖 (最高优先级, 便于临时 -s/env 覆盖) ──
    def _apply_env_overrides(self):
        for key in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER",
                    "MYSQL_PASSWORD", "MYSQL_DATABASE"):
            val = os.getenv(key)
            if val:
                if key == "MYSQL_PORT":
                    try:
                        setattr(self, key, int(val))
                    except ValueError:
                        pass
                else:
                    setattr(self, key, val)

    # ── 派生属性 ────────────────────────────────────────────

    @property
    def json_output_base_dir(self) -> str:
        """JSON 输出的基础目录 (根); 子类或环境变量可覆盖"""
        return os.getenv("ACADEMIC_JSON_OUTPUT", self._json_base_dir)

    @property
    def json_output_dir(self) -> str:
        """JSON 输出的完整目录 = 基础目录 + 模式子目录"""
        base = self.json_output_base_dir
        sub = self.json_subdir
        return os.path.join(base, sub) if sub else base

    @property
    def log_dir(self) -> Path:
        """文件日志目录: PROJECT_ROOT/logs[/<subdir>] (subdir 见 log_subdir)"""
        base = PROJECT_ROOT / "logs"
        sub = log_subdir(self.mode)
        return base if not sub else base / sub

    # ── 判定 ────────────────────────────────────────────────

    @property
    def is_test(self) -> bool:
        return self.mode == "test"

    @property
    def is_dev(self) -> bool:
        return self.mode == "dev"

    @property
    def is_prod(self) -> bool:
        return self.mode == "prod"

    # ── 展示 ────────────────────────────────────────────────

    def summarize(self) -> str:
        pw = self.MYSQL_PASSWORD
        masked = (pw[:1] + "*" * (len(pw) - 1)) if pw else "(未设置)"
        return (
            f"[{self.mode}] {self.label}\n"
            f"  数据库: {self.MYSQL_DATABASE} @ {self.MYSQL_HOST}:{self.MYSQL_PORT}\n"
            f"  用户:   {self.MYSQL_USER}\n"
            f"  密码:   {masked}\n"
            f"  日志:   {self.log_dir}\n"
            f"  JSON:   {self.json_output_dir}"
        )
