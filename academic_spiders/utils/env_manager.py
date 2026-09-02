"""
环境/模式配置管理器 (EnvManager)

统一管理三种运行模式 (test / dev / prod) 的 MySQL 等环境变量配置，
把"手工复制粘贴 .env 块"的繁琐方式替换为一行命令切换。

三种模式 (与 .env.profiles 仓库对应):
  - test: 本地测试   academicdb_test @ localhost
  - dev : 本地开发   academicdb       @ localhost
  - prod: 远程生产   pubscholar       @ 远程主机 (需连接 VPN/内网)

Profile 仓库: 项目根目录 .env.profiles (gitignored, 含真实密钥)
  文件按段组织, 每段以 `[<mode>]` 开头, 内容为 KEY=VALUE 行,
  每段即一个完整可写入 .env 的配置块。

切换原理 (重写 .env):
  1. 读取 .env.profiles 中目标模式的配置块;
  2. 与当前 .env 合并: profile 键整体覆盖, .env 中非 profile 键 (自定义) 保留;
  3. 生成新 .env 并原子写入 (临时文件 + os.replace), 旧 .env 备份为 .env.bak;
  4. settings.py 通过 load_dotenv() 读取 .env, 无需改动运行逻辑。
"""

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import dotenv_values

from academic_spiders.utils.logging_config import (
    PROJECT_ROOT,
    get_log_dir,
    is_test_db,
)

logger = logging.getLogger(__name__)

# 三种模式定义 (顺序即文档/展示顺序)
MODES: Tuple[str, ...] = ("test", "dev", "prod")

# 每模式的标记环境变量名 (写入 .env, 供日志目录分流等判断)
MODE_ENV_VAR = "ACADEMIC_MODE"

# Profile 仓库文件 (gitignored, 含真实密钥)
DEFAULT_PROFILES_FILE = PROJECT_ROOT / ".env.profiles"
# 模板文件 (可提交)
EXAMPLE_PROFILES_FILE = PROJECT_ROOT / ".env.profiles.example"
# 活动配置文件 (settings.py load_dotenv 加载)
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# 段头格式: [test]
_SECTION_RE = re.compile(r"^\s*\[(?P<mode>[a-zA-Z0-9_]+)\]\s*$")


@dataclass
class Profile:
    """单个模式配置块"""
    mode: str
    comment: str                 # 段注释 (模式中文名)
    env: Dict[str, str]          # KEY=VALUE 有序 dict (Python 3.7+ 保序)


class EnvError(Exception):
    """配置管理相关错误 (缺失文件/未知模式/字段不完整)"""


class EnvManager:
    """环境模式切换管理器"""

    def __init__(
        self,
        profiles_file: Optional[Path] = None,
        env_file: Optional[Path] = None,
    ):
        self.profiles_file = Path(profiles_file) if profiles_file else DEFAULT_PROFILES_FILE
        self.env_file = Path(env_file) if env_file else DEFAULT_ENV_FILE

    # ── Profile 读取 ────────────────────────────────────────

    def read_profiles(self) -> List[Profile]:
        """解析 .env.profiles 为有序 Profile 列表 (保持文件内顺序)"""
        if not self.profiles_file.exists():
            raise EnvError(
                f"Profile 仓库不存在: {self.profiles_file}\n"
                "请先创建 (可参考同目录 .env.profiles.example, 或运行 env.py init)"
            )
        profiles: List[Profile] = []
        pending_comments: List[str] = []
        cur: Optional[Profile] = None
        with open(self.profiles_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    pending_comments.append(stripped.lstrip("#").strip())
                    continue
                m = _SECTION_RE.match(stripped)
                if m:
                    comment = pending_comments[-1] if pending_comments else ""
                    cur = Profile(mode=m.group("mode"), comment=comment, env={})
                    profiles.append(cur)
                    pending_comments = []
                    continue
                if cur is not None and "=" in stripped:
                    key, _, value = stripped.partition("=")
                    cur.env[key.strip()] = value.strip()
        return profiles

    def get_profile(self, mode: str) -> Profile:
        """获取指定模式的 Profile, 未知模式抛 EnvError"""
        for p in self.read_profiles():
            if p.mode == mode:
                return p
        raise EnvError(
            f"未知模式: {mode} (可用: {', '.join(self.mode_names())})"
        )

    def mode_names(self) -> List[str]:
        return [p.mode for p in self.read_profiles()]

    # ── 当前 .env 状态 ─────────────────────────────────────

    def read_active_env(self) -> Dict[str, str]:
        """读取当前 .env (不存在则返回空)"""
        if not self.env_file.exists():
            return {}
        values = dotenv_values(self.env_file)
        return {k: str(v) for k, v in values.items() if v is not None}

    def detect_active_mode(self) -> Optional[str]:
        """根据 .env 内容反推当前模式

        优先级: ACADEMIC_MODE 标记 > MYSQL_DATABASE 库名匹配
        """
        active_env = self.read_active_env()
        marker = (active_env.get(MODE_ENV_VAR) or "").strip().lower()
        profiles = self.read_profiles()
        if marker in [p.mode for p in profiles]:
            return marker
        db = active_env.get("MYSQL_DATABASE")
        if not db:
            return None
        host = active_env.get("MYSQL_HOST")
        for p in profiles:
            p_db = p.env.get("MYSQL_DATABASE")
            p_host = p.env.get("MYSQL_HOST")
            if p_db == db and (not host or not p_host or p_host == host):
                return p.mode
        return None

    # ── 写入 .env ──────────────────────────────────────────

    def collect_extra(self) -> Dict[str, str]:
        """收集 .env 中不属于任何 profile 的自定义键 (切换时需保留)"""
        active_env = self.read_active_env()
        profile_keys = set()
        for p in self.read_profiles():
            profile_keys.update(p.env.keys())
        return {
            k: v for k, v in active_env.items()
            if k not in profile_keys and k != MODE_ENV_VAR
        }

    def render(self, mode: str) -> str:
        """生成目标模式 .env 的完整内容 (profile + 保留的自定义键)"""
        profile = self.get_profile(mode)
        lines = [f"# {profile.comment}"] if profile.comment else []
        lines.append(f"# Auto-generated by env.py: mode = {profile.mode}")
        for key, value in profile.env.items():
            lines.append(f"{key}={value}")
        extra_env = self.collect_extra()
        if extra_env:
            lines.append("")
            lines.append("# Extra (自定义, 保留自原 .env)")
            for key, value in extra_env.items():
                lines.append(f"{key}={value}")
        return "\n".join(lines) + "\n"

    def write_env(self, mode: str):
        """把目标模式的渲染结果写入 .env (原子替换 + 备份旧文件)

        :param mode: 目标模式 (test/dev/prod)
        """
        content = self.render(mode)

        # 备份旧 .env
        if self.env_file.exists():
            backup = self.env_file.parent / ".env.bak"
            backup.write_text(
                self.env_file.read_text(encoding="utf-8"), encoding="utf-8"
            )
            logger.info("已备份原 .env → %s", backup)

        # 原子写入
        fd, tmp_path = tempfile.mkstemp(
            dir=self.env_file.parent, prefix=".env.tmp", text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, self.env_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.info("已写入 .env → 模式 %s", mode)

    def switch(self, mode: str):
        """切换到指定模式并写 .env"""
        profile = self.get_profile(mode)
        self.write_env(mode)
        return profile

    # ── 便捷查询 (供 CLI / 其它模块) ────────────────────────

    def summary(self) -> Dict[str, object]:
        """汇总当前状态: 模式 / 数据库 / 日志目录 / 是否测试"""
        active_env = self.read_active_env()
        mode = self.detect_active_mode()
        db = active_env.get("MYSQL_DATABASE", "")
        log_dir = get_log_dir(db) if db else None
        return {
            "mode": mode,
            "db": db,
            "is_test": is_test_db(db) if db else None,
            "log_dir": log_dir,
            "profiles": [p.mode for p in self.read_profiles()],
        }
