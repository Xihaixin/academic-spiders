"""
下载器中间件: API 签名注入、Cookie 注入 & 重试控制

支持双域名:
  - pubscholar.cn (v1 开放接口)
  - scholarin.cn   (v2 登录接口)

签名算法相同: SHA1(sorted([secret, timestamp, nonce]).join(""))
"""

import logging
from scrapy.downloadermiddlewares.retry import RetryMiddleware

from academic_spiders.utils.signing import build_signature_headers

logger = logging.getLogger(__name__)


class PubscholarSigningMiddleware:
    """
    请求拦截中间件: 对 pubscholar.cn / scholarin.cn 注入:
      1. 签名头 (nonce / timestamp / signature / x-finger)
      2. CSRF Token (X-XSRF-TOKEN)
      3. 会话 Cookie
    """

    def __init__(self, secret: str, domain_configs: dict):
        self.secret = secret
        self.configs = domain_configs  # {domain: {finger, xsrf_token, cookie}}

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        return cls(
            secret=s.get("PUBSCHOLAR_SECRET", ""),
            domain_configs={
                "pubscholar.cn": {
                    "finger": s.get("V1_FINGER", ""),
                    "xsrf_token": s.get("V1_XSRF_TOKEN", ""),
                    "cookie": s.get("V1_COOKIE", ""),
                },
                "scholarin.cn": {
                    "finger": s.get("V2_FINGER", ""),
                    "xsrf_token": s.get("V2_XSRF_TOKEN", ""),
                    "cookie": s.get("V2_COOKIE", ""),
                },
            },
        )

    def _get_config(self, url: str) -> dict:
        """根据 URL 域名获取对应配置"""
        for domain, config in self.configs.items():
            if domain in url:
                return config
        return {}

    def process_request(self, request, spider):
        """在请求发出前注入签名头和认证信息"""
        config = self._get_config(request.url)
        if not config:
            return None  # 非目标域名，跳过

        # 1. 动态签名头
        sig_headers = build_signature_headers(
            self.secret, config.get("finger", "")
        )
        for key, value in sig_headers.items():
            request.headers[key] = value

        # 2. CSRF Token
        xsrf = config.get("xsrf_token", "")
        if xsrf:
            request.headers["X-XSRF-TOKEN"] = xsrf

        # 3. 会话 Cookie
        cookie = config.get("cookie", "")
        if cookie:
            request.headers["Cookie"] = cookie

        return None


class PubscholarRetryMiddleware(RetryMiddleware):
    """
    扩展重试中间件: 429/403 时刷新签名并指数退避
    """

    def __init__(self, settings):
        super().__init__(settings)
        self.secret = settings.get("PUBSCHOLAR_SECRET", "")
        # 使用 v1 finger 作为默认（重试时刷新签名即可）
        self.fallback_finger = (
            settings.get("V1_FINGER")
            or settings.get("V2_FINGER")
            or ""
        )

    def _is_target(self, url: str) -> bool:
        return "pubscholar.cn" in url or "scholarin.cn" in url

    def _retry(self, request, reason, spider):
        """重试前刷新签名"""
        retry_req = super()._retry(request, reason, spider)
        if retry_req and self._is_target(request.url):
            sig_headers = build_signature_headers(
                self.secret, self.fallback_finger
            )
            for key, value in sig_headers.items():
                retry_req.headers[key] = value
        return retry_req

    def process_response(self, request, response, spider):
        if response.status in (429, 403):
            reason = "频率限制" if response.status == 429 else "权限/签名问题"
            logger.warning(
                "HTTP %d (%s): %s", response.status, reason, request.url,
            )
            return self._retry(request, reason, spider) or response
        return response
