"""
配置系统: 以"配置类 + 注册表"管理三种运行模式 (test/dev/prod)

替代旧方案 (整块重写 .env): .env 现在只保存单一开关 ACADEMIC_MODE;
模式的具体值定义在代码子类中 (modes.py), 敏感字段存 .env.secrets。
"""

from academic_spiders.config.base import ConfigBase
from academic_spiders.config.registry import (
    get_active_config,
    get_active_mode,
    list_modes,
    set_active_mode,
)

__all__ = [
    "ConfigBase",
    "get_active_config",
    "get_active_mode",
    "list_modes",
    "set_active_mode",
]
