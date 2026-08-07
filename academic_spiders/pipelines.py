"""
数据管道: JSON 原样输出 + MySQL 存储
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

import pymysql
from dbutils.pooled_db import PooledDB
from scrapy import signals

logger = logging.getLogger(__name__)


# ============================================================
# JSON 导出管道: 将原始 Item 输出到 ./output/ 目录
# ============================================================
class JsonExportPipeline:
    """按页码分批保存原始响应到 JSON 文件"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.buffers: dict = {}  # page -> [items]

    @classmethod
    def from_crawler(cls, crawler):
        output_dir = os.path.join(
            crawler.settings.get("PROJECT_DIR", "."), "output"
        )
        os.makedirs(output_dir, exist_ok=True)
        return cls(output_dir=output_dir)

    def process_item(self, item):
        page = item.get("_page", "unknown")
        if page not in self.buffers:
            self.buffers[page] = []
        # 转为普通 dict 存储
        self.buffers[page].append(dict(item))
        return item

    def close_spider(self):
        for page, items in self.buffers.items():
            filename = os.path.join(
                self.output_dir, f"page_{page:06d}.json"
            )
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            logger.info("已保存 %d 条到 %s", len(items), filename)


# ============================================================
# MySQL 管道: 多表写入
# ============================================================
class MySQLPipeline:
    """将 Item 写入 MySQL 数据库（articles + 子表 + spiders_run_log）"""

    def __init__(self, settings: dict):
        self.pool: Optional[PooledDB] = None
        self.settings = settings
        self._run_id: Optional[str] = None
        self._spider_name: str = ""
        self._start_time: Optional[datetime] = None
        self._item_count: int = 0
        self._error_count: int = 0
        self._last_page: int = 0
        self._init_pool()

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(settings=crawler.settings)
        crawler.signals.connect(instance._on_spider_opened, signals.spider_opened)
        crawler.signals.connect(instance.close_spider, signals.spider_closed)
        return instance

    def _on_spider_opened(self, spider):
        self._spider_name = spider.name
        self._start_time = datetime.now()
        self._run_id = uuid.uuid4().hex
        self._insert_run_log("running")

    def _init_pool(self):
        """初始化 MySQL 连接池"""
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

    def close_spider(self):
        self._update_run_log("completed")
        if self.pool:
            self.pool.close()
            logger.info("MySQL 连接池已关闭")

    def process_item(self, item):
        self._item_count += 1
        self._last_page = max(self._last_page, item.get("_page", 0) or 0)
        try:
            conn = self.pool.connection()
            try:
                article_id = self._upsert_article(conn, item)
                self._sync_authors(conn, article_id, item)
                self._sync_keywords(conn, article_id, item)
                self._upsert_extended_data(conn, article_id, item)
                self._upsert_thesis_info(conn, article_id, item)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception as e:
            self._error_count += 1
            logger.error("写入 MySQL 失败 [%s]: %s", item.get("article_md5"), e)
        return item

    # ── articles 主表 ────────────────────────────────────────

    def _upsert_article(self, conn, item) -> int:
        """写入或更新 articles 表，返回自增 id"""
        sql = """
            INSERT INTO articles (
                article_md5, title, abstracts, key_words, author_names,
                source, volume, issue, first_page, last_page,
                date, year, doi, cstr,
                type, article_type, lang, cn_type,
                is_free, links
            ) VALUES (
                %(article_md5)s, %(title)s, %(abstracts)s, %(key_words)s, %(author_names)s,
                %(source)s, %(volume)s, %(issue)s, %(first_page)s, %(last_page)s,
                %(date)s, %(year)s, %(doi)s, %(cstr)s,
                %(type)s, %(article_type)s, %(lang)s, %(cn_type)s,
                %(is_free)s, %(links)s
            ) ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                abstracts = VALUES(abstracts),
                key_words = VALUES(key_words),
                author_names = VALUES(author_names),
                source = VALUES(source),
                volume = VALUES(volume),
                issue = VALUES(issue),
                first_page = VALUES(first_page),
                last_page = VALUES(last_page),
                date = VALUES(date),
                year = VALUES(year),
                doi = VALUES(doi),
                cstr = VALUES(cstr),
                type = VALUES(type),
                article_type = VALUES(article_type),
                lang = VALUES(lang),
                cn_type = VALUES(cn_type),
                is_free = VALUES(is_free),
                links = VALUES(links),
                updated_at = NOW()
        """
        params = self._extract_article_params(item)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            article_id = cur.lastrowid
            # 如果是更新操作 lastrowid 为 0，需要查询
            if article_id == 0:
                cur.execute(
                    "SELECT id FROM articles WHERE article_md5 = %s",
                    (item.get("article_md5"),),
                )
                row = cur.fetchone()
                article_id = row["id"] if row else 0
        return article_id

    def _extract_article_params(self, item) -> dict:
        """从 Item 提取 articles 表参数"""
        return {
            "article_md5": item.get("article_md5", ""),
            "title": item.get("title", ""),
            "abstracts": item.get("abstracts", ""),
            "key_words": self._to_json(item.get("key_words")),
            "author_names": self._to_json(item.get("author_names")),
            "source": item.get("source", ""),
            "volume": item.get("volume", ""),
            "issue": item.get("issue", ""),
            "first_page": item.get("first_page", ""),
            "last_page": item.get("last_page", ""),
            "date": item.get("date", ""),
            "year": self._to_int(item.get("year")),
            "doi": item.get("doi", ""),
            "cstr": item.get("cstr", ""),
            "type": item.get("type", ""),
            "article_type": item.get("article_type", ""),
            "lang": item.get("lang", "zh"),
            "cn_type": item.get("cn_type", ""),
            "is_free": 1 if item.get("is_free") else 0,
            "links": self._to_json(item.get("links")),
        }

    # ── article_authors 子表 ─────────────────────────────────

    def _sync_authors(self, conn, article_id: int, item):
        """同步作者数据: 先删后插"""
        article_md5 = item.get("article_md5", "")
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
                sql = """
                    INSERT INTO article_authors
                        (article_id, article_md5, author_name,
                         is_corresponding, institutions, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cur.execute(sql, (
                    article_id,
                    article_md5,
                    author.get("name", ""),
                    1 if author.get("is_corresponding_author") else 0,
                    self._to_json(author.get("institution", [])),
                    idx,
                ))

    # ── article_keywords 子表 ────────────────────────────────

    def _sync_keywords(self, conn, article_id: int, item):
        """同步关键词: 先删后插（中文+英文关键词分别入库）"""
        article_md5 = item.get("article_md5", "")

        # 收集关键词
        keywords_zh = []
        keywords_en = []

        # 从 key_words 字段
        kw = item.get("key_words") or []
        if isinstance(kw, str):
            try:
                kw = json.loads(kw)
            except json.JSONDecodeError:
                kw = []
        for k in kw:
            if k not in keywords_zh:
                keywords_zh.append(k)

        # 从 extend_entity 中提取 cnKeywords / enKeywords
        ext = item.get("extend_entity") or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except json.JSONDecodeError:
                ext = {}
        for k in (ext.get("cnKeywords") or []):
            if k not in keywords_zh:
                keywords_zh.append(k)
        for k in (ext.get("enKeywords") or []):
            if k not in keywords_en:
                keywords_en.append(k)

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM article_keywords WHERE article_id = %s",
                (article_id,),
            )
            for idx, kw in enumerate(keywords_zh):
                cur.execute(
                    """INSERT INTO article_keywords
                       (article_id, article_md5, keyword, lang, sort_order)
                       VALUES (%s, %s, %s, 'zh', %s)""",
                    (article_id, article_md5, kw, idx),
                )
            for idx, kw in enumerate(keywords_en):
                cur.execute(
                    """INSERT INTO article_keywords
                       (article_id, article_md5, keyword, lang, sort_order)
                       VALUES (%s, %s, %s, 'en', %s)""",
                    (article_id, article_md5, kw, idx),
                )

    # ── article_extended_data 子表 ────────────────────────────

    def _upsert_extended_data(self, conn, article_id: int, item):
        """写入扩展数据"""
        article_md5 = item.get("article_md5", "")
        sql = """
            INSERT INTO article_extended_data
                (article_id, article_md5, extend_entity, semantic_entities,
                 source_list, license, local_links, attachments)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                extend_entity = VALUES(extend_entity),
                semantic_entities = VALUES(semantic_entities),
                source_list = VALUES(source_list),
                license = VALUES(license),
                local_links = VALUES(local_links),
                attachments = VALUES(attachments)
        """
        with conn.cursor() as cur:
            cur.execute(sql, (
                article_id,
                article_md5,
                self._to_json(item.get("extend_entity")),
                self._to_json(item.get("semantic_entities")),
                self._to_json(item.get("source_list")),
                item.get("license", ""),
                self._to_json(item.get("local_links")),
                self._to_json(item.get("attachments")),
            ))

    # ── article_thesis_info 子表 ─────────────────────────────

    def _upsert_thesis_info(self, conn, article_id: int, item):
        """仅对学位论文写入 thesis_info"""
        cn_type = (item.get("cn_type") or "").strip()
        if "学位" not in cn_type:
            return

        article_md5 = item.get("article_md5", "")
        sql = """
            INSERT INTO article_thesis_info
                (article_id, article_md5, degree, major, school,
                 tutor, graduation_institution)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                degree = VALUES(degree),
                major = VALUES(major),
                school = VALUES(school),
                tutor = VALUES(tutor),
                graduation_institution = VALUES(graduation_institution)
        """
        with conn.cursor() as cur:
            cur.execute(sql, (
                article_id,
                article_md5,
                item.get("degree", ""),
                item.get("major", ""),
                self._to_json(item.get("school")),
                self._to_json(item.get("tutor")),
                self._to_json(item.get("graduation_institution")),
            ))

    # ── spider_run_log ────────────────────────────────────────

    def _insert_run_log(self, status: str):
        """插入运行日志起始记录"""
        try:
            conn = self.pool.connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO spider_run_log
                           (run_id, spider_name, start_time, status)
                           VALUES (%s, %s, %s, %s)""",
                        (self._run_id, self._spider_name,
                         self._start_time, status),
                    )
                conn.commit()
            finally:
                conn.close()
            logger.info("spider_run_log 已写入: run_id=%s", self._run_id[:12])
        except Exception as e:
            logger.warning("无法写入 spider_run_log: %s", e)

    def _update_run_log(self, status: str):
        """更新运行日志 (结束时间、状态、统计)"""
        try:
            conn = self.pool.connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE spider_run_log SET
                           end_time = %s,
                           status = %s,
                           total_items = %s,
                           total_errors = %s,
                           last_page = %s
                           WHERE run_id = %s""",
                        (datetime.now(), status, self._item_count,
                         self._error_count, self._last_page,
                         self._run_id),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("无法更新 spider_run_log: %s", e)

    # ── 辅助方法 ─────────────────────────────────────────────

    @staticmethod
    def _to_json(value):
        """将 Python 对象转为 JSON 字符串，已是字符串则原样返回"""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _to_int(value):
        """安全转整数"""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
