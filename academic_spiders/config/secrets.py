"""
敏感配置加载器 (.env.secrets)

存放各模式真正的密钥/基础设施信息 (gitignored, 不提交仓库):

  [test]
  MYSQL_PASSWORD=xxx

  [dev]
  MYSQL_PASSWORD=xxx

  [prod]
  MYSQL_HOST=xxx
  MYSQL_PORT=3306
  MYSQL_USER=xxx
  MYSQL_PASSWORD=xxx

模板见 .env.secrets.example (可提交, 占位符)。缺文件/缺段时不报错,
由模式子类保留内置默认 (非敏感部分); 敏感字段缺失则连接时自然失败。
"""

import re
from pathlib import Path
from typing import Dict, Optional

from academic_spiders.utils.logging_config import PROJECT_ROOT

DEFAULT_SECRETS_FILE = PROJECT_ROOT / ".env.secrets"
EXAMPLE_SECRETS_FILE = PROJECT_ROOT / ".env.secrets.example"

_SECTION_RE = re.compile(r"^\s*\[(?P<mode>[a-zA-Z0-9_]+)\]\s*$")

# 允许在 secrets 文件中出现并可合并到 ConfigBase 的键
ALLOWED_KEYS = (
    "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER",
    "MYSQL_PASSWORD", "MYSQL_DATABASE",
)


def load_secrets(mode: str, path: Optional[Path] = None) -> Dict[str, str]:
    """读取 .env.secrets 中指定模式的敏感字段 (不存在/缺段 → 空 dict)"""
    path = Path(path) if path else DEFAULT_SECRETS_FILE
    if not path.exists():
        return {}
    current: Optional[str] = None
    result: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = _SECTION_RE.match(stripped)
            if m:
                current = m.group("mode")
                continue
            if current == mode and "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                if key in ALLOWED_KEYS:
                    result[key] = value.strip()
    return result
