"""
日志配置工具: 控制台 + 文件双输出

供 settings.py (Scrapy) 和 run_*_spider.py (Windows runner) 复用。

日志目录规则 (三模式隔离, v3.5):
  - prod (远程库 pubscholar):    logs/<文件名>.log
  - dev  (本地库 academicdb):    logs/dev/<文件名>.log
  - test (本地测试库 academicdb_test 等): logs/test/<文件名>.log

模式判定 (单一开关 ACADEMIC_MODE, 与 config 注册表一致):
  1. 环境变量 ACADEMIC_MODE (env.py 写入 .env, 唯一真相);
  2. 缺省时按 MYSQL_DATABASE 库名反推 (pubscholar→prod, academicdb→dev, 其余→test);
  3. 都缺省时默认 dev (本地开发, 安全侧)。

轮转: 单文件 50MB 触发轮转, 保留 10 个历史文件 (.1 ~ .10)。
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# 项目根目录 (utils/ 的上一级是 academic_spiders/, 再上一级是项目根)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

LOG_FORMAT_FULL = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFORMAT_FULL = "%Y-%m-%d %H:%M:%S"

# 三种运行模式
MODES = ("test", "dev", "prod")

DEFAULT_MODE = "dev"

# 库名 → 模式 (ACADEMIC_MODE 缺省时的反推表; 未列出的库名一律按 test 处理)
_DB_TO_MODE = {
    "pubscholar": "prod",
    "academicdb": "dev",
}

# 模式 → logs/ 下的子目录 (None/空串 = logs/ 根目录, 即 prod)
_MODE_LOG_SUBDIR = {
    "prod": "",
    "dev": "dev",
    "test": "test",
}


def mode_env_marker() -> str:
    """读取 ACADEMIC_MODE 环境变量 (env.py 在 .env 中维护)"""
    return os.getenv("ACADEMIC_MODE", "").strip().lower()


def resolve_db_name(db_name: str) -> str:
    """解析数据库名: 优先传入值, 其次环境变量 MYSQL_DATABASE"""
    if db_name:
        return db_name
    return os.getenv("MYSQL_DATABASE", "")


def mode_of_db(db_name: str) -> str:
    """库名 → 模式 (未识别库名按 test 安全处理)"""
    name = resolve_db_name(db_name)
    return _DB_TO_MODE.get(name, "test")


def resolve_mode(db_name: Optional[str] = None) -> str:
    """解析当前模式: ACADEMIC_MODE 优先, 其次按库名反推, 最后默认 dev"""
    marker = mode_env_marker()
    if marker in MODES:
        return marker
    name = resolve_db_name(db_name or "")
    if name:
        return mode_of_db(name)
    return DEFAULT_MODE


def log_subdir(mode: str) -> str:
    """模式 → logs/ 下的子目录名 (prod 返回空串 = logs/ 根目录)"""
    return _MODE_LOG_SUBDIR.get(mode, _MODE_LOG_SUBDIR["test"])


def is_test_db(db_name: Optional[str] = None) -> bool:
    """判断当前是否为 test 模式"""
    return resolve_mode(db_name) == "test"


def is_prod_db(db_name: Optional[str] = None) -> bool:
    """判断当前是否为 prod 模式 (远程库 pubscholar)"""
    return resolve_mode(db_name) == "prod"


def get_log_dir(db_name: Optional[str] = None) -> Path:
    """获取 (并创建) 日志目录

    :param db_name: 数据库名 (None 时按 ACADEMIC_MODE / 环境变量 MYSQL_DATABASE 解析模式)
    :return: prod → logs/; dev → logs/dev/; test → logs/test/
    """
    mode = resolve_mode(db_name)
    base = PROJECT_ROOT / "logs"
    sub = log_subdir(mode)
    if sub:
        base = base / sub
    base.mkdir(parents=True, exist_ok=True)
    return base


def setup_file_logging(
    log_filename: str,
    level: int = logging.INFO,
    db_name: Optional[str] = None,
):
    """为 root logger 添加轮转文件 handler (保留控制台输出)

    :param log_filename: 日志文件名 (如 "runner_v1.log")
    :param level:        日志级别
    :param db_name:      数据库名。None 时按 ACADEMIC_MODE / MYSQL_DATABASE 解析模式。
                          日志目录跟随模式: prod→logs/, dev→logs/dev/, test→logs/test/
    :return: 创建的 handler
    """
    handler = RotatingFileHandler(
        get_log_dir(db_name) / log_filename,
        maxBytes=50 * 1024 * 1024,   # 50MB 触发轮转
        backupCount=10,               # 保留 10 个历史文件 (.1 ~ .10)
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        LOG_FORMAT_FULL, datefmt=LOG_DATEFORMAT_FULL
    ))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    return handler
