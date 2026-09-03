"""
配置注册表: 模式选择与激活配置对象管理

选择逻辑 (单一开关):
  .env 中 ACADEMIC_MODE=test|dev|prod (由 env.py switch 维护);
  缺省/非法值回退默认模式 dev。

对外 API:
  get_active_mode()                → str  当前激活模式名
  get_active_config()              → ConfigBase 激活配置对象 (含 secrets, 缓存)
  build_config(mode, refresh)      → ConfigBase 指定模式配置对象 (可强制重建)
  set_active_mode(mode, persist)   → 程序内切换激活模式 (persist=True 时同步写 .env)
  list_modes()                     → [(mode, label, is_active), ...]
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple

from academic_spiders.config.base import ConfigBase
from academic_spiders.config.modes import DevConfig, ProdConfig, TestConfig
from academic_spiders.config.secrets import load_secrets
from academic_spiders.utils.logging_config import PROJECT_ROOT

# 模式注册表 (顺序即展示顺序)
MODE_CLASSES = {
    "test": TestConfig,
    "dev": DevConfig,
    "prod": ProdConfig,
}

DEFAULT_MODE = "dev"
MODE_ENV_VAR = "ACADEMIC_MODE"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# 当前进程内激活配置对象 (缓存)
_active_config: Optional[ConfigBase] = None


def _read_active_mode_env() -> str:
    """读取 ACADEMIC_MODE (含 .env 中设置), 非法值回退默认"""
    mode = (os.getenv(MODE_ENV_VAR) or "").strip().lower()
    return mode if mode in MODE_CLASSES else DEFAULT_MODE


def get_active_mode() -> str:
    return _read_active_mode_env()


def build_config(mode: Optional[str] = None, refresh: bool = False) -> ConfigBase:
    """构造指定模式 (默认激活模式) 的配置对象, 合并 secrets"""
    global _active_config
    mode = (mode or get_active_mode()).strip().lower()
    if mode not in MODE_CLASSES:
        mode = DEFAULT_MODE
    if refresh or _active_config is None or _active_config.mode != mode:
        cls = MODE_CLASSES[mode]
        secrets = load_secrets(mode)
        _active_config = cls(secrets=secrets)
    return _active_config


def get_active_config(refresh: bool = False) -> ConfigBase:
    """当前激活配置对象 (含 secrets)"""
    return build_config(refresh=refresh)


def set_active_mode(mode: str, persist: bool = True) -> ConfigBase:
    """切换激活模式

    :param persist: True 时同步把 ACADEMIC_MODE 写入 .env (永久生效)
    :return: 新激活配置对象
    """
    mode = mode.strip().lower()
    if mode not in MODE_CLASSES:
        raise ValueError(
            f"未知模式: {mode} (可用: {', '.join(MODE_CLASSES)})"
        )
    os.environ[MODE_ENV_VAR] = mode
    if persist:
        _write_env_mode(mode)
    return build_config(refresh=True)


def _write_env_mode(mode: str):
    """把 ACADEMIC_MODE=<mode> 写入 .env (保留其它键, 原子替换该行)"""
    env_file = Path(os.getenv("ACADEMIC_ENV_FILE", DEFAULT_ENV_FILE))
    content = ""
    replaced = False
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            if line.strip().startswith(MODE_ENV_VAR + "="):
                out.append(f"{MODE_ENV_VAR}={mode}")
                replaced = True
            else:
                out.append(line)
        content = "\n".join(out)
    if not replaced:
        content = (content + "\n" if content else "") + f"{MODE_ENV_VAR}={mode}"
    env_file.write_text(content + "\n", encoding="utf-8")


def list_modes() -> List[Tuple[str, str, bool]]:
    """列出所有模式: [(mode, label, is_active), ...]"""
    active = get_active_mode()
    result = []
    for mode, cls in MODE_CLASSES.items():
        cfg = cls.__new__(cls)   # 不触发 secrets 合并, 只取静态 label
        result.append((mode, getattr(cfg, "label", ""), mode == active))
    return result
