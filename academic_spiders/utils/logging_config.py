"""
日志配置工具: 控制台 + 文件双输出

供 settings.py (Scrapy) 和 run_*_spider.py (Windows runner) 复用。
日志文件位于项目根目录 logs/ 下，50MB 轮转，保留 10 个历史文件。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 项目根目录 (utils/ 的上一级是 academic_spiders/, 再上一级是项目根)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

LOG_FORMAT_FULL = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFORMAT_FULL = "%Y-%m-%d %H:%M:%S"


def get_log_dir() -> Path:
    """获取 (并创建) logs 目录"""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def setup_file_logging(log_filename: str, level: int = logging.INFO):
    """为 root logger 添加轮转文件 handler (保留控制台输出)

    :param log_filename: 日志文件名 (如 "runner_v1.log")
    :param level:        日志级别
    :return: 创建的 handler
    """
    handler = RotatingFileHandler(
        get_log_dir() / log_filename,
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
