# Scrapy settings for academic_spiders project

BOT_NAME = "academic_spiders"

SPIDER_MODULES = ["academic_spiders.spiders"]
NEWSPIDER_MODULE = "academic_spiders.spiders"

# ── 爬虫行为 ──────────────────────────────────────────────────
ROBOTSTXT_OBEY = False
COOKIES_ENABLED = False         # 禁用 Scrapy 默认 Cookie 管理，由签名中间件直接注入 Cookie header
TELNETCONSOLE_ENABLED = False
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFORMAT = "%H:%M:%S"

# ── 并发控制 ──────────────────────────────────────────────────
CONCURRENT_REQUESTS = 8
DOWNLOAD_DELAY = 1.5
RANDOMIZE_DOWNLOAD_DELAY = True

# ── 自动限速 ──────────────────────────────────────────────────
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0

# ── 重试与错误处理 ────────────────────────────────────────────
RETRY_ENABLED = True
RETRY_TIMES = 3
# 403 由 PubscholarRetryMiddleware 单独处理（含签名刷新），
# 避免与 Scrapy 内置 RetryMiddleware 双重重试
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

# ── 下载器中间件 ──────────────────────────────────────────────
DOWNLOADER_MIDDLEWARES = {
    "academic_spiders.middlewares.PubscholarSigningMiddleware": 543,
    "academic_spiders.middlewares.PubscholarRetryMiddleware": 550,
}

# ── Item Pipeline ─────────────────────────────────────────────
ITEM_PIPELINES = {
    "academic_spiders.pipelines.JsonExportPipeline": 100,
    "academic_spiders.pipelines.MySQLPipeline": 200,
}

# ── MySQL 配置 ────────────────────────────────────────────────
MYSQL_HOST = "localhost"
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_PASSWORD = "200310"
MYSQL_DATABASE = "academicdb"
MYSQL_POOL_SIZE = 8

# ── Feed 导出 ─────────────────────────────────────────────────
FEED_EXPORT_ENCODING = "utf-8"

# ── 请求头 (基础头，签名头由中间件动态注入) ────────────────────
DEFAULT_REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"
    ),
    "Origin": "https://pubscholar.cn",
    "Referer": "https://pubscholar.cn/",
    # 同源标记（关键！）
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# ── Cookie / 认证配置 (通过 cookies.json + 环境变量加载) ────
from academic_spiders.utils.cookie_config import load_cookie_config
_cookie_cfg = load_cookie_config()
_v1cfg = _cookie_cfg["v1"]
_v2cfg = _cookie_cfg["v2"]

# ── v1 API 配置 ───────────────────────────────────────────────
PUBSCHOLAR_V1_URL = "https://pubscholar.cn/hky/open/resources/api/v1/articles"
PUBSCHOLAR_SECRET = _v1cfg["secret"]
PUBSCHOLAR_USER_ID = _v1cfg["user_id"]
V1_COOKIE = _v1cfg["cookie"]
V1_XSRF_TOKEN = _v1cfg["xsrf_token"]
V1_FINGER = _v1cfg["finger"]

# ── 爬取控制 ──────────────────────────────────────────────────
V1_MAX_PAGES = None
V1_PAGE_SIZE = _v1cfg["page_size"]
V1_START_PAGE = 1
V1_YEAR_FROM = None
V1_YEAR_TO = None

# ── v2 API 配置 ───────────────────────────────────────────────
V2_API_URL = "https://scholarin.cn/hky/api/v2/resources/article"
V2_QUERY = ""
V2_MAX_PAGES = None
V2_PAGE_SIZE = _v2cfg["page_size"]
V2_START_PAGE = 1
V2_COOKIE = _v2cfg["cookie"]
V2_XSRF_TOKEN = _v2cfg["xsrf_token"]
V2_USER_ID = _v2cfg["user_id"]
V2_FINGER = _v2cfg["finger"]
