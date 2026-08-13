"""
测试数据库初始化工具
────────────────────
创建/重置与生产环境完全隔离的测试数据库，表结构相同。

用法:
  python init_test_db.py                 # 创建 academicdb_test 并建表 (如不存在)
  python init_test_db.py --reset         # 重置: 删除重建 (清空所有测试数据)
  python init_test_db.py --db-name my_test_db   # 自定义测试库名

建表脚本: sql/schema.sql (与生产环境完全一致)
"""

import argparse
import logging
import sys
from pathlib import Path

import pymysql

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("init_test_db")

PROJECT_ROOT = Path(__file__).parent
SCHEMA_FILE = PROJECT_ROOT / "sql" / "schema.sql"


def split_sql_statements(sql: str):
    """拆分 SQL 脚本为可执行语句 (跳过注释)"""
    statements = []
    for stmt in sql.split(";"):
        lines = [l for l in stmt.split("\n")
                 if not l.strip().startswith("--")]
        clean = "\n".join(lines).strip()
        # 去除块注释
        while "/*" in clean:
            start = clean.index("/*")
            end = clean.index("*/", start) + 2
            clean = clean[:start] + clean[end:]
        if clean:
            statements.append(clean)
    return statements


def create_database(host, port, user, password, db_name, reset):
    """创建测试数据库 (连接 MySQL 服务器, 不指定 database)"""
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            if reset:
                logger.info("删除旧测试库: %s", db_name)
                cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        logger.info("测试数据库已就绪: %s", db_name)
    finally:
        conn.close()


def create_tables(host, port, user, password, db_name):
    """在测试库中执行 schema.sql 建表"""
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    statements = split_sql_statements(schema_sql)

    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=db_name, charset="utf8mb4",
    )
    try:
        created, skipped = 0, 0
        with conn.cursor() as cur:
            for stmt in statements:
                try:
                    cur.execute(stmt)
                    created += 1
                except Exception as e:
                    skipped += 1
                    logger.debug("跳过语句: %s", e)
        conn.commit()
        logger.info("建表完成: %d 条语句, %d 条跳过", created, skipped)
    finally:
        conn.close()


def show_tables(host, port, user, password, db_name):
    """列出测试库中的表"""
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=db_name, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
        logger.info("测试库 %s 的表: %s", db_name, ", ".join(tables))
        return tables
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="测试数据库初始化工具 (与生产环境完全隔离)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python init_test_db.py                          # 创建测试库 + 建表
  python init_test_db.py --reset                  # 重置测试库 (清空数据)
  python init_test_db.py --db-name my_test_db     # 自定义库名
        """,
    )
    parser.add_argument("--db-name", type=str, default="academicdb_test",
                        help="测试数据库名 (默认 academicdb_test)")
    parser.add_argument("--reset", action="store_true",
                        help="重置: 删除并重建 (清空所有测试数据)")
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", type=str, default="root")
    parser.add_argument("--password", type=str, default="200310")
    args = parser.parse_args()

    try:
        # 1. 创建测试数据库
        create_database(
            args.host, args.port, args.user, args.password,
            args.db_name, args.reset,
        )
        # 2. 建表
        create_tables(
            args.host, args.port, args.user, args.password,
            args.db_name,
        )
        # 3. 展示结果
        show_tables(
            args.host, args.port, args.user, args.password,
            args.db_name,
        )
        logger.info("✅ 测试数据库初始化完成: %s", args.db_name)
        logger.info("使用方式: scrapy crawl pubscholar_v1 -s MYSQL_DATABASE=%s", args.db_name)
        logger.info("     或: python run_v1_spider.py --db-name %s", args.db_name)
    except Exception as e:
        logger.error("初始化失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
