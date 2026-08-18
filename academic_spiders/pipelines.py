"""
数据管道: JSON 原样输出 + MySQL 存储 (v3.2)
"""

import json
import logging
import os
import uuid
from typing import Optional

import pymysql
from dbutils.pooled_db import PooledDB
from scrapy import signals
from scrapy.settings import Settings

logger = logging.getLogger(__name__)


# ============================================================
# JSON 导出管道
# ============================================================
class JsonExportPipeline:
    """按页码分批保存到 ./output/ 目录"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.buffers: dict = {}

    @classmethod
    def from_crawler(cls, crawler):
        project_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        output_dir = crawler.settings.get("ACADEMIC_JSON_OUTPUT")
        if crawler.settings.get("MYSQL_DATABASE") == "academicdb_test":
            output_dir = os.path.join(output_dir, "test")
            
        os.makedirs(output_dir, exist_ok=True)
        return cls(output_dir=output_dir)

    def process_item(self, item, spider=None):
        page = item.get("_page", "unknown")
        if page not in self.buffers:
            self.buffers[page] = []
        self.buffers[page].append(dict(item))
        return item

    def close_spider(self, spider=None):
        for page, items in self.buffers.items():
            filename = os.path.join(
                self.output_dir, f"page_{page:06d}.json"
            )
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            logger.info("已保存 %d 条到 %s", len(items), filename)


# ============================================================
# MySQL 管道 (4 张业务表)
#   articles → article_authors → article_keywords → article_thesis_info
# ============================================================
class MySQLPipeline:
    """将 Item 写入 MySQL 数据库"""

    def __init__(self, settings: Settings):
        self.pool: Optional[PooledDB] = None
        self.settings = settings
        self._init_pool()

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(settings=crawler.settings)
        crawler.signals.connect(instance.close_spider, signals.spider_closed)
        return instance

    def _init_pool(self):
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=self.settings.getint("MYSQL_POOL_SIZE", 8),
            mincached=2,
            maxcached=4,
            blocking=True,
            host=self.settings.get("MYSQL_HOST"),
            port=self.settings.getint("MYSQL_PORT"),
            user=self.settings.get("MYSQL_USER"),
            password=self.settings.get("MYSQL_PASSWORD"),
            database=self.settings.get("MYSQL_DATABASE"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        logger.info("MySQL 连接池已初始化")

    def close_spider(self, spider=None):
        if self.pool:
            self.pool.close()
            logger.info("MySQL 连接池已关闭")

    def process_item(self, item, spider=None):
        if self.pool is None:
            return item
        try:
            conn = self.pool.connection()
            try:
                article_id = self._upsert_article(conn, item)
                self._sync_authors(conn, article_id, item)
                self._sync_keywords(conn, article_id, item)
                self._upsert_thesis_info(conn, article_id, item)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception as e:
            logger.error(
                "写入 MySQL 失败 [%s]: %s",
                item.get("doi") or item.get("title"), e,
            )
        return item

    # ── articles 主表 ────────────────────────────────────────

    def _upsert_article(self, conn, item) -> int:
        """写入 articles 表 (带去重), 返回自增 id

        流程:
          1. dedup_key 为空 → 直接 INSERT
          2. dedup_key 非空 → SELECT 查询是否已存在
             - 已存在 → 旧数据写审计表 + UPDATE
             - 不存在 → INSERT (ON DUPLICATE KEY UPDATE 兜底竞态)
        """
        dedup_key = item.get("dedup_key")

        # 无 dedup_key → 直接插入
        if not dedup_key:
            return self._insert_article(conn, item)

        # 查询是否已存在
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM articles WHERE dedup_key = %s", (dedup_key,)
            )
            old_row = cur.fetchone()

        if old_row:
            # 已存在 → 审计 + UPDATE
            new_params = self._extract_article_params(item)
            self._audit_update(conn, old_row, dedup_key, new_params)
            self._update_article(conn, old_row["id"], new_params)
            return old_row["id"]

        # 不存在 → INSERT (兜底竞态)
        return self._insert_article(conn, item)

    def _insert_article(self, conn, item) -> int:
        """插入 articles 表, 返回自增 id"""
        sql = """
            INSERT INTO articles (
                dedup_key, title, abstracts,
                key_words, cn_keywords, en_keywords,
                author_names, contrib_institutions,
                source, volume, issue, first_page, last_page,
                date, year, doi, cstr,
                article_type, lang, links
            ) VALUES (
                %(dedup_key)s, %(title)s, %(abstracts)s,
                %(key_words)s, %(cn_keywords)s, %(en_keywords)s,
                %(author_names)s, %(contrib_institutions)s,
                %(source)s, %(volume)s, %(issue)s, %(first_page)s, %(last_page)s,
                %(date)s, %(year)s, %(doi)s, %(cstr)s,
                %(article_type)s, %(lang)s, %(links)s
            ) ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                abstracts = VALUES(abstracts),
                key_words = VALUES(key_words),
                cn_keywords = VALUES(cn_keywords),
                en_keywords = VALUES(en_keywords),
                author_names = VALUES(author_names),
                contrib_institutions = VALUES(contrib_institutions),
                source = VALUES(source),
                volume = VALUES(volume),
                issue = VALUES(issue),
                first_page = VALUES(first_page),
                last_page = VALUES(last_page),
                date = VALUES(date),
                year = VALUES(year),
                doi = VALUES(doi),
                cstr = VALUES(cstr),
                article_type = VALUES(article_type),
                lang = VALUES(lang),
                links = VALUES(links),
                updated_at = NOW()
        """
        params = self._extract_article_params(item)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid

    def _update_article(self, conn, article_id: int, params: dict):
        """更新 articles 表已有记录"""
        sql = """
            UPDATE articles SET
                title = %(title)s,
                abstracts = %(abstracts)s,
                key_words = %(key_words)s,
                cn_keywords = %(cn_keywords)s,
                en_keywords = %(en_keywords)s,
                author_names = %(author_names)s,
                contrib_institutions = %(contrib_institutions)s,
                source = %(source)s,
                volume = %(volume)s,
                issue = %(issue)s,
                first_page = %(first_page)s,
                last_page = %(last_page)s,
                date = %(date)s,
                year = %(year)s,
                doi = %(doi)s,
                cstr = %(cstr)s,
                article_type = %(article_type)s,
                lang = %(lang)s,
                links = %(links)s,
                updated_at = NOW()
            WHERE id = %(article_id)s
        """
        with conn.cursor() as cur:
            params = dict(params)
            params["article_id"] = article_id
            cur.execute(sql, params)

    def _audit_update(self, conn, old_row: dict, dedup_key: str, new_params: dict):
        """把被覆盖的旧数据快照写入审计表"""
        old_data = json.dumps(old_row, ensure_ascii=False, default=str)
        new_data = json.dumps(new_params, ensure_ascii=False, default=str)
        sql = """
            INSERT INTO articles_audit_log
                (article_id, dedup_key, old_data, new_data)
            VALUES (%s, %s, %s, %s)
        """
        with conn.cursor() as cur:
            cur.execute(
                sql, (old_row["id"], dedup_key, old_data, new_data)
            )
        logger.info(
            "去重命中: article_id=%d, dedup_key=%s",
            old_row["id"], dedup_key[:60],
        )

    def _extract_article_params(self, item) -> dict:
        return {
            "dedup_key": item.get("dedup_key"),
            "title": item.get("title", ""),
            "abstracts": item.get("abstracts", ""),
            "key_words": self._to_json(item.get("key_words")),
            "cn_keywords": self._to_json(item.get("cn_keywords")),
            "en_keywords": self._to_json(item.get("en_keywords")),
            "author_names": self._to_json(item.get("author_names")),
            "contrib_institutions": self._to_json(
                item.get("contrib_institutions")
            ),
            "source": item.get("source", ""),
            "volume": item.get("volume", ""),
            "issue": item.get("issue", ""),
            "first_page": item.get("first_page", ""),
            "last_page": item.get("last_page", ""),
            "date": item.get("date", ""),
            "year": self._to_int(item.get("year")),
            "doi": item.get("doi", ""),
            "cstr": item.get("cstr", ""),
            "article_type": item.get("article_type", ""),
            "lang": item.get("lang", "zh"),
            "links": self._to_json(item.get("links")),
        }

    # ── article_authors 子表 ─────────────────────────────────

    def _sync_authors(self, conn, article_id: int, item):
        authors = item.get("authors") or []
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except json.JSONDecodeError:
                authors = []

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM article_authors WHERE article_id = %s",
                (article_id,),
            )
            for idx, author in enumerate(authors):
                if not isinstance(author, dict):
                    continue
                cur.execute(
                    """INSERT INTO article_authors
                       (article_id, author_name, author_id,
                        is_corresponding, institutions, sort_order)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        article_id,
                        author.get("name", ""),
                        author.get("author_id"),
                        1 if author.get("is_corresponding_author") else 0,
                        self._to_json(author.get("institution", [])),
                        idx,
                    ),
                )

    # ── article_keywords 子表 ────────────────────────────────

    def _sync_keywords(self, conn, article_id: int, item):
        """同步关键词: 从 key_words + cn_keywords + en_keywords 三源汇总"""
        keywords_zh = []
        keywords_en = []

        def _extract(source, lang, seen):
            data = source
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return
            for kw in (data or []):
                if kw and kw not in seen:
                    seen.append(kw)
                    if lang == "zh":
                        keywords_zh.append(kw)
                    else:
                        keywords_en.append(kw)

        _extract(item.get("key_words"), "zh", [])
        _extract(item.get("cn_keywords"), "zh", keywords_zh)
        _extract(item.get("en_keywords"), "en", keywords_en)

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM article_keywords WHERE article_id = %s",
                (article_id,),
            )
            for idx, kw in enumerate(keywords_zh):
                cur.execute(
                    """INSERT INTO article_keywords
                       (article_id, keyword, lang, sort_order)
                       VALUES (%s, %s, 'zh', %s)""",
                    (article_id, kw, idx),
                )
            for idx, kw in enumerate(keywords_en):
                cur.execute(
                    """INSERT INTO article_keywords
                       (article_id, keyword, lang, sort_order)
                       VALUES (%s, %s, 'en', %s)""",
                    (article_id, kw, idx),
                )

    # ── article_thesis_info 子表 ─────────────────────────────

    def _upsert_thesis_info(self, conn, article_id: int, item):
        article_type = (item.get("article_type") or "").strip()
        if article_type != "学位论文":
            return

        sql = """
            INSERT INTO article_thesis_info
                (article_id, degree, major, school,
                 tutor, graduation_institution)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                degree = VALUES(degree),
                major = VALUES(major),
                school = VALUES(school),
                tutor = VALUES(tutor),
                graduation_institution = VALUES(graduation_institution)
        """
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    article_id,
                    item.get("degree", ""),
                    item.get("major", ""),
                    self._to_json(item.get("school")),
                    self._to_json(item.get("tutor")),
                    self._to_json(item.get("graduation_institution")),
                ),
            )

    # ── 辅助方法 ─────────────────────────────────────────────

    @staticmethod
    def _to_json(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _to_int(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
