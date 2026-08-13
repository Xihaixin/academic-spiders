"""
日志配置工具: 控制台 + 文件双输出

供 settings.py (Scrapy) 和 run_*_spider.py (Windows runner) 复用。

日志目录规则 (测试/生产隔离):
  - 生产库 (academicdb):        logs/<文件名>.log
  - 其他库 (如 academicdb_test): logs/test/<文件名>.log

轮转: 单文件 50MB 触发轮转, 保留 10 个历史文件 (.1 ~ .10)。
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 项目根目录 (utils/ 的上一级是 academic_spiders/, 再上一级是项目根)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

LOG_FORMAT_FULL = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFORMAT_FULL = "%Y-%m-%d %H:%M:%S"

# 生产数据库名 (其他名字视为测试环境, 日志写入 logs/test/)
PROD_DB_NAME = "academicdb"


def resolve_db_name(db_name: str) -> str:
    """解析数据库名: 优先传入值, 其次环境变量 MYSQL_DATABASE"""
    if db_name:
        return db_name
    return os.getenv("MYSQL_DATABASE", "")


def is_test_db(db_name: str) -> bool:
    """判断是否为测试环境 (数据库名非生产库名)"""
    return bool(db_name) and db_name != PROD_DB_NAME


def get_log_dir(db_name: str = None) -> Path:
    """获取 (并创建) 日志目录

    :param db_name: 数据库名 (None 时从环境变量读取)
    :return: 生产 → logs/; 测试 → logs/test/
    """
    name = resolve_db_name(db_name or "")
    base = PROJECT_ROOT / "logs"
    if is_test_db(name):
        base = base / "test"
    base.mkdir(parents=True, exist_ok=True)
    return base


def setup_file_logging(
    log_filename: str,
    level: int = logging.INFO,
    db_name: str = None,
):
    """为 root logger 添加轮转文件 handler (保留控制台输出)

    :param log_filename: 日志文件名 (如 "runner_v1.log")
    :param level:        日志级别
    :param db_name:      数据库名。None 时从 MYSQL_DATABASE 环境变量读取。
                         非生产库时日志写入 logs/test/ 子目录 (与生产隔离)
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
