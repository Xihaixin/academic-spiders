"""
断点续爬工具: 从 spider_run_log 表查询上次运行的最后页码
"""

import logging
from typing import Optional, Sequence

import pymysql

logger = logging.getLogger(__name__)

# 查询时匹配 Scrapy spider 名称
# (v1 仅分桶模式, 断点续爬走 crawl_query_state, 不在此查询)
V1_SPIDER_NAMES = ("pubscholar_v1",)
V2_SPIDER_NAMES = ("pubscholar_v2",)


def get_last_page(config, spider_names: Sequence[str]) -> Optional[int]:
    """查询最近一次运行的最后页码

    :param config:       数据库配置 (Scrapy Settings 或 dict, 需含 MYSQL_* 键)
    :param spider_names:  要匹配的 spider 名称序列 (取最近一次)
    :return:             最后页码; None = 无历史记录或查询失败
    """
    try:
        conn = pymysql.connect(
            host=config.get("MYSQL_HOST"),
            port=config.get("MYSQL_PORT", 3306),
            user=config.get("MYSQL_USER"),
            password=config.get("MYSQL_PASSWORD"),
            database=config.get("MYSQL_DATABASE"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(spider_names))
                cur.execute(
                    f"""SELECT last_page, spider_name, status, end_time
                        FROM spider_run_log
                        WHERE spider_name IN ({placeholders})
                          AND last_page > 0
                        ORDER BY id DESC LIMIT 1""",
                    tuple(spider_names),
                )
                row = cur.fetchone()
                if row:
                    logger.info(
                        "检测到上次运行记录: spider=%s, status=%s, "
                        "last_page=%d, end_time=%s",
                        row["spider_name"], row["status"],
                        row["last_page"], row["end_time"],
                    )
                    return row["last_page"]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("查询断点续爬记录失败: %s", e)

    return None


def resolve_start_page(config, spider_names: Sequence[str]) -> int:
    """解析起始页码: 上次断点 + 1, 无记录则从 1 开始

    :return: 起始页码 (>= 1)
    """
    last_page = get_last_page(config, spider_names)
    if last_page:
        return last_page + 1
    return 1
