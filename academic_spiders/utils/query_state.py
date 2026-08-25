"""
查询桶状态记录器 (crawl_query_state 表)
─────────────────────────────────────
供 v1 聚合分桶模式使用:
  - 幂等插入叶子桶 (query_hash 唯一), 支持批量插入 (计划构建期)
  - 领取 pending 桶 → running (断点续爬核心)
  - 更新进度 / 标记完成或失败

使用持久连接 + 批量插入, 避免计划构建期 (数千叶子桶) 的逐条连接开销。
"""

import hashlib
import json
import logging
import uuid
from typing import Dict, List, Optional

import pymysql
import pymysql.cursors
from scrapy.settings import Settings

from academic_spiders.utils.api_client import AGG_FILTER_KEYS

logger = logging.getLogger(__name__)


def query_hash(filters: dict) -> str:
    """由筛选参数生成稳定唯一哈希 (所有 11 个聚合键, 固定顺序)"""
    canonical = json.dumps(
        {k: str(filters.get(k, "")) for k in AGG_FILTER_KEYS},
        ensure_ascii=False,
    )
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


class QueryStateStore:
    """crawl_query_state 表访问层 (持久连接, 失败时自动重连)"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.run_id = str(uuid.uuid4())
        self._conn: Optional[pymysql.connections.Connection] = None

    def _connect(self):
        return pymysql.connect(
            host=self.settings.get("MYSQL_HOST"),
            port=self.settings.getint("MYSQL_PORT"),
            user=self.settings.get("MYSQL_USER"),
            password=self.settings.get("MYSQL_PASSWORD"),
            database=self.settings.get("MYSQL_DATABASE"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _get_conn(self):
        if self._conn is None or not self._conn.open:
            self._conn = self._connect()
        return self._conn

    def close(self):
        """释放持久连接"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ── 生命周期 ────────────────────────────────────────────

    def mark_interrupted(self):
        """启动时把上次异常终止遗留的 running 桶重置为 pending"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE crawl_query_state SET status='pending' "
                    "WHERE status='running'"
                )
            conn.commit()
            logger.info("已将遗留 running 桶重置为 pending (断点续爬)")
        except Exception as e:
            logger.warning("重置中断桶状态失败: %s", e)

    # ── 桶操作 ──────────────────────────────────────────────

    def insert_many(self, buckets: List[dict]):
        """批量幂等插入叶子桶 (executemany, 单连接)

        :param buckets: [{filters, total, max_page, page_size, collection}, ...]
        """
        if not buckets:
            return
        rows = [
            (
                self.run_id,
                query_hash(b["filters"]),
                json.dumps(b["filters"], ensure_ascii=False),
                b.get("collection"),
                int(b["total"]),
                int(b.get("page_size", 50)),
                int(b["max_page"]),
            )
            for b in buckets
        ]
        sql = (
            "INSERT IGNORE INTO crawl_query_state "
            "(run_id, query_hash, query_params, collection, total, "
            " page_size, max_page, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')"
        )
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            conn.commit()
        except Exception as e:
            logger.warning("批量插入桶失败 (%d 条): %s", len(rows), e)

    def insert_bucket(self, filters: dict, total: int, max_page: int,
                      page_size: int, collection: Optional[str] = None):
        """幂等插入单个叶子桶 (已存在则忽略)"""
        self.insert_many([{
            "filters": filters, "total": total, "max_page": max_page,
            "page_size": page_size, "collection": collection,
        }])

    def claim_next(self) -> Optional[dict]:
        """领取一个 pending 桶 (置为 running), 返回其查询参数与边界"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, query_hash, query_params, total, max_page
                       FROM crawl_query_state
                       WHERE status='pending'
                       ORDER BY id ASC LIMIT 1
                       FOR UPDATE"""
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """UPDATE crawl_query_state SET
                               status='running', run_id=%s, start_time=NOW(),
                               cur_page=0, items_collected=0, error_message=NULL
                           WHERE id=%s""",
                        (self.run_id, row["id"]),
                    )
                conn.commit()
            return row
        except Exception as e:
            logger.warning("领取桶失败: %s", e)
        return None

    def update_progress(self, query_hash_: str, page: int, items: int):
        """更新桶进度 (页码 + 累计条数)"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE crawl_query_state SET
                           cur_page = %s,
                           items_collected = items_collected + %s
                       WHERE query_hash = %s""",
                    (page, items, query_hash_),
                )
            conn.commit()
        except Exception as e:
            logger.warning("更新桶进度失败 [%s]: %s", query_hash_[:8], e)

    def mark_done(self, query_hash_: str, status: str, error: Optional[str] = None):
        """标记桶完成/失败"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE crawl_query_state SET
                           status = %s, end_time = NOW(), error_message = %s
                       WHERE query_hash = %s""",
                    (status, error, query_hash_),
                )
            conn.commit()
        except Exception as e:
            logger.warning("标记桶状态失败 [%s]: %s", query_hash_[:8], e)

    def summary(self) -> Dict[str, int]:
        """各状态桶数量 (用于日志/验证)"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, COUNT(*) AS n FROM crawl_query_state GROUP BY status"
                )
                rows = cur.fetchall()
            return {r["status"]: r["n"] for r in rows}
        except Exception as e:
            logger.warning("统计桶状态失败: %s", e)
        return {}

    # ── 计划标记 (续爬跳过重建) ──────────────────────────────

    @staticmethod
    def _plan_key(collections, threshold: int, depth: int) -> str:
        raw = f"{','.join(sorted(collections))}|{threshold}|{depth}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def plan_exists(self, collections, threshold: int, depth: int) -> bool:
        """是否已存在匹配当前配置的完整分桶计划"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM crawl_plan WHERE plan_key=%s LIMIT 1",
                    (self._plan_key(collections, threshold, depth),),
                )
                return cur.fetchone() is not None
        except Exception as e:
            logger.warning("查询分桶计划标记失败: %s", e)
        return False

    def plan_mark(self, collections, threshold: int, depth: int, bucket_count: int):
        """记录分桶计划已构建完成"""
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO crawl_plan
                       (plan_key, collections, threshold, depth, bucket_count, created_at)
                       VALUES (%s, %s, %s, %s, %s, NOW())
                       ON DUPLICATE KEY UPDATE
                           bucket_count = VALUES(bucket_count),
                           created_at = NOW()""",
                    (
                        self._plan_key(collections, threshold, depth),
                        ",".join(sorted(collections)),
                        int(threshold), int(depth), int(bucket_count),
                    ),
                )
            conn.commit()
        except Exception as e:
            logger.warning("记录分桶计划标记失败: %s", e)
