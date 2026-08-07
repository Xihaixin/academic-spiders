"""
Cookie 配置加载器

优先顺序: 环境变量 > cookies.json > 默认值
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 默认项目根目录下的 cookies 文件
DEFAULT_COOKIES_FILE = Path(__file__).parent.parent.parent / "cookies.json"


def load_cookie_config(path: Optional[str] = None) -> Dict[str, dict]:
    """加载 cookies.json 配置，环境变量可覆盖

    环境变量映射:
      PUBSCHOLAR_V1_COOKIE     → v1.cookie
      PUBSCHOLAR_V1_XSRF_TOKEN → v1.xsrf_token
      PUBSCHOLAR_V1_FINGER     → v1.finger
      PUBSCHOLAR_V1_USER_ID    → v1.user_id
      PUBSCHOLAR_V2_COOKIE     → v2.cookie
      PUBSCHOLAR_V2_XSRF_TOKEN → v2.xsrf_token
      PUBSCHOLAR_V2_FINGER     → v2.finger
      PUBSCHOLAR_V2_USER_ID    → v2.user_id
    """
    config = {
        "v1": {
            "cookie": "", "xsrf_token": "", "finger": "", "user_id": "",
            "secret": "6m6pingbinwaktg227gngifoocrfbo95", "page_size": 50,
        },
        "v2": {
            "cookie": "", "xsrf_token": "", "finger": "", "user_id": "",
            "secret": "6m6pingbinwaktg227gngifoocrfbo95", "page_size": 20,
        },
    }

    # 从 cookies.json 读取
    file_path = Path(path) if path else DEFAULT_COOKIES_FILE
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            for ver in ("v1", "v2"):
                if ver in file_config:
                    config[ver].update(file_config[ver])
            logger.info("已从 %s 加载 Cookie 配置", file_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("无法读取 %s: %s，使用默认值", file_path, e)
    else:
        logger.info("%s 不存在，使用默认值 (v1: %s)", file_path, file_path)

    # 环境变量覆盖
    _env_override(config["v1"], "PUBSCHOLAR_V1")
    _env_override(config["v2"], "PUBSCHOLAR_V2")

    return config


def _env_override(cfg: dict, prefix: str):
    """读取环境变量覆盖配置"""
    for key in ("COOKIE", "XSRF_TOKEN", "FINGER", "USER_ID"):
        env_key = f"{prefix}_{key}"
        val = os.getenv(env_key)
        if val:
            cfg[key.lower()] = val
