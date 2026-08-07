"""
Cookie 健康检查与自动登录模块

CSTCloud Passport (passport.escience.cn) 登录流程:
  1. GET passport.escience.cn/login → 提取 _csrf token
  2. POST /login (username + password + csrf) 
  3. 重定向回 pubscholar.cn → 获取 pub_ticket + XSRF-TOKEN

pub_ticket 有效期: ~10 天，过期后必须重新登录，无续期接口。
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

from academic_spiders.utils.signing import build_signature_headers

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
V1_API_URL = "https://pubscholar.cn/hky/open/resources/api/v1/articles"
PASSPORT_LOGIN_URL = "https://passport.escience.cn/login"
PUB_HOME_URL = "https://pubscholar.cn"
SECRET = "6m6pingbinwaktg227gngifoocrfbo95"
FINGER = "c84069ed4e4270f9897e3a07acb81355"
DEFAULT_USER_ID = "0b68c4370e9a43e4ad1690fdd31f643f"

COOKIES_FILE = Path(__file__).parent.parent.parent / "cookies.json"


# ── Cookie 验证 ──────────────────────────────────────────────

def check_cookie_valid(cookie: str, xsrf_token: str) -> Tuple[bool, str]:
    """验证 Cookie 是否有效

    :returns: (is_valid, detail_message)
    """
    session = _build_session(cookie, xsrf_token)
    try:
        r = session.post(
            V1_API_URL,
            json={"page": 1, "size": 1, "order_field": "date",
                  "order_direction": "desc", "user_id": DEFAULT_USER_ID,
                  "lang": "zh",
                  "aggregations": {"type": "", "subject": "", "year": "",
                                   "keyword": "", "collection": "", "lang": "C",
                                   "source": "", "correspAuthor": "", "funding": "",
                                   "institution": "", "license": ""}},
            timeout=15,
        )
        if r.status_code != 200:
            return False, f"API 返回 HTTP {r.status_code}"
        data = r.json()
        if data.get("failure"):
            return False, f"API 错误: {data.get('cause', '未知')}"
        total = data.get("total", 0)
        return True, f"有效 (总计 {total:,} 条)"
    except Exception as e:
        return False, f"请求异常: {e}"


def _build_session(cookie: str, xsrf_token: str) -> requests.Session:
    """构建带签名的 requests Session"""
    session = requests.Session()
    for item in cookie.split(";"):
        item = item.strip()
        if "=" in item:
            name, _, value = item.partition("=")
            session.cookies.set(name.strip(), value.strip(), domain="pubscholar.cn")

    sig = build_signature_headers(SECRET, FINGER)
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"),
        "Origin": "https://pubscholar.cn",
        "Referer": "https://pubscholar.cn/",
        "X-XSRF-TOKEN": xsrf_token,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        **sig,
    })
    return session


# ── 自动登录 ──────────────────────────────────────────────────

def auto_login(username: str, password: str) -> Optional[dict]:
    """通过 CSTCloud Passport 自动登录，返回新的 Cookie 配置

    如果登录页面出现验证码则返回 None（需人工介入）。
    """
    logger.info("开始自动登录: %s", username)
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"
    )

    # Step 1: 获取登录页面，提取 CSRF token
    return_url = "https://pubscholar.cn/"
    login_page_url = f"{PASSPORT_LOGIN_URL}?returnUrl={requests.utils.quote(return_url)}"

    try:
        r = session.get(login_page_url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.error("获取登录页面失败: %s", e)
        return None

    csrf = _extract_csrf(r.text)
    if not csrf:
        logger.error("无法提取登录页 CSRF token")
        return None
    logger.debug("CSRF token: %s", csrf[:20])

    # Step 2: 检查是否有验证码
    if "captcha" in r.text.lower() or "ValidCodeImage" in r.text:
        logger.warning("登录页面包含验证码，自动登录失败，需要人工介入")
        logger.info("请手动访问 %s 登录后更新 cookies.json", login_page_url)
        return None

    # Step 3: 提交登录表单
    login_data = {
        "username": username,
        "password": password,
        "_csrf": csrf,
        "act": "Validate",
    }

    try:
        r = session.post(
            f"{PASSPORT_LOGIN_URL}?returnUrl={requests.utils.quote(return_url)}",
            data=login_data,
            headers={
                "Origin": "https://passport.escience.cn",
                "Referer": login_page_url,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            allow_redirects=True,
            timeout=30,
        )
        logger.debug("登录响应 URL: %s [%d]", r.url, r.status_code)
    except Exception as e:
        logger.error("登录请求失败: %s", e)
        return None

    # Step 4: 检查是否登录成功（最终应重定向到 pubscholar.cn）
    domain = r.url.split("/")[2] if "//" in r.url else ""
    if "pubscholar.cn" not in domain:
        # 可能仍在 passport 域
        if "账号或密码错误" in r.text or "error" in r.text.lower():
            logger.error("登录失败: 账号或密码错误")
            return None
        # 尝试跟随隐藏的重定向
        if "ticket=" in r.text or "pub_ticket" in r.text:
            logger.info("响应中发现 ticket 或 pub_ticket")
        else:
            logger.warning("登录后未跳转到 pubscholar.cn，当前页面: %s", domain)
            # 尝试直接访问 pubscholar.cn 获取 cookie
            try:
                session.get(PUB_HOME_URL, timeout=10)
            except Exception:
                pass

    # Step 5: 提取 Cookie
    cookies = session.cookies
    pub_ticket = cookies.get("pub_ticket", domain="pubscholar.cn")
    xsrf_token = cookies.get("XSRF-TOKEN", domain="pubscholar.cn")
    # 如果上面获取不到，尝试不带 domain 查询
    if not pub_ticket:
        pub_ticket = cookies.get("pub_ticket")
    if not xsrf_token:
        xsrf_token = cookies.get("XSRF-TOKEN")

    if not pub_ticket:
        logger.error("登录后未获取到 pub_ticket cookie")
        logger.debug("所有 cookies: %s", [(c.name, c.value[:20]) for c in cookies])
        return None

    raw_cookie = "; ".join(
        f"{c.name}={c.value}" for c in cookies
        if c.name in ("pub_ticket", "XSRF-TOKEN")
    )

    cfg = {
        "cookie": raw_cookie,
        "xsrf_token": xsrf_token or "",
        "finger": FINGER,
        "user_id": DEFAULT_USER_ID,
        "secret": SECRET,
        "page_size": 50,
    }

    logger.info("自动登录成功, pub_ticket=%s..., xsrf=%s...",
                pub_ticket[:20], (xsrf_token or "")[:20])
    return cfg


def _extract_csrf(html: str) -> Optional[str]:
    """从 HTML 中提取 CSRF token"""
    for marker in ('<meta name="_csrf" content="', 'name="_csrf" content="',
                   '_csrf" value="', 'csrf" content="'):
        pos = html.find(marker)
        if pos > 0:
            start = pos + len(marker)
            end = html.find('"', start)
            if end > start:
                return html[start:end]
    return None


# ── Cookie 持久化 ─────────────────────────────────────────────

def save_cookies(v1_cfg: dict, v2_cfg: Optional[dict] = None):
    """保存 Cookie 配置到 cookies.json"""
    config = {"v1": v1_cfg}
    if v2_cfg is None:
        # 保留原有 v2 配置
        if COOKIES_FILE.exists():
            try:
                existing = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
                config["v2"] = existing.get("v2", {})
            except Exception:
                config["v2"] = {}
        else:
            config["v2"] = {}
    else:
        config["v2"] = v2_cfg

    COOKIES_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    logger.info("Cookie 已保存到 %s", COOKIES_FILE)


def load_v1_cookies() -> dict:
    """加载 v1 Cookie 配置"""
    if COOKIES_FILE.exists():
        try:
            cfg = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            return cfg.get("v1", {})
        except Exception:
            pass
    return {}


# ── 命令行工具 ────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="慧科研 Cookie 管理工具")
    sub = parser.add_subparsers(dest="cmd")

    check_parser = sub.add_parser("check", help="检查当前 Cookie 有效性")
    login_parser = sub.add_parser("login", help="自动登录并更新 Cookie")
    login_parser.add_argument("-u", "--username", required=True, help="CSTCloud 账号")
    login_parser.add_argument("-p", "--password", required=True, help="密码")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.cmd == "check":
        cfg = load_v1_cookies()
        if not cfg.get("cookie"):
            print("❌ 未找到 Cookie 配置 (cookies.json 不存在或 v1.cookie 为空)")
            return
        valid, msg = check_cookie_valid(cfg["cookie"], cfg.get("xsrf_token", ""))
        print(f"{'✅' if valid else '❌'} {msg}")

    elif args.cmd == "login":
        cfg = auto_login(args.username, args.password)
        if cfg:
            valid, msg = check_cookie_valid(cfg["cookie"], cfg["xsrf_token"])
            print(f"登录后验证: {'✅' if valid else '❌'} {msg}")
            if valid:
                save_cookies(cfg)
                print("✅ Cookie 已更新")
            else:
                print("❌ 登录成功但 Cookie 无效，请检查账号权限")
        else:
            print("❌ 自动登录失败")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
