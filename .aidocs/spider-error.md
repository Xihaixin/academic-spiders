# 爬虫错误

目前在运行爬虫过程中遇到两种不同类型的错误

## 第一类 SSL.Error


2026-09-04 10:32:00 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure OpenSSL.SSL.Error: [('SSL routines', '', 'tls alert handshake failure')]>]
2026-09-04 10:32:02 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure OpenSSL.SSL.Error: [('SSL routines', '', 'tls alert handshake failure')]>]
2026-09-04 10:32:04 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure OpenSSL.SSL.Error: [('SSL routines', '', 'tls alert handshake failure')]>]
2026-09-04 10:32:06 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 2 times): [<twisted.python.failure.Failure OpenSSL.SSL.Error: [('SSL routines', '', 'tls alert handshake failure')]>]
2026-09-04 10:32:08 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure OpenSSL.SSL.Error: [('SSL routines', '', 'tls alert handshake failure')]>]

### error connection
2026-09-04 15:38:37 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure twisted.internet.error.ConnectionLost: Connection to the other side was lost in a non-clean fashion: Connection lost.>]

2026-09-04 16:21:51 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])


## 第二类  Connection to the other side was lost in a non-clean fashion

2026-09-04 16:23:08 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure twisted.internet.error.ConnectionLost: Connection to the other side was lost in a non-clean fashion: Connection lost.>]
2026-09-04 16:23:08 [DEBUG] scrapy.downloadermiddlewares.retry: Retrying <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (failed 1 times): [<twisted.python.failure.Failure twisted.internet.error.ConnectionLost: Connection to the other side was lost in a non-clean fashion: Connection lost.>]


## 第三类 Remote certificate is not valid

2026-09-04 16:42:09 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:10 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:10 [WARNING] academic_spiders.spiders.pubscholar_v1: 桶 f7d4ee1b 第 2 页失败 (Ignoring non-200 response), 重试 1/3
2026-09-04 16:42:11 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:12 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:12 [WARNING] academic_spiders.spiders.pubscholar_v1: 桶 f7d4ee1b 第 1 页失败 (Ignoring non-200 response), 重试 2/3
2026-09-04 16:42:14 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:14 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:14 [WARNING] academic_spiders.spiders.pubscholar_v1: 桶 4387153c 第 5 页失败 (Ignoring non-200 response), 重试 1/3
2026-09-04 16:42:16 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:16 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:16 [WARNING] academic_spiders.spiders.pubscholar_v1: 桶 4387153c 第 6 页失败 (Ignoring non-200 response), 重试 2/3
2026-09-04 16:42:17 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:17 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:17 [WARNING] academic_spiders.spiders.pubscholar_v1: 桶 4387153c 第 7 页失败 (Ignoring non-200 response), 重试 3/3
2026-09-04 16:42:18 [INFO] scrapy.extensions.logstats: Crawled 5069 pages (at 33 pages/min), scraped 249299 items (at 1348 items/min)
2026-09-04 16:42:19 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:19 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:19 [WARNING] academic_spiders.spiders.pubscholar_v1: 桶 f7d4ee1b 第 5 页失败 (Ignoring non-200 response), 重试 3/3
2026-09-04 16:42:21 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:21 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:21 [ERROR] academic_spiders.spiders.pubscholar_v1: 桶失败: qhash=f7d4ee1b, 原因=Ignoring non-200 response
2026-09-04 16:42:21 [INFO] academic_spiders.spiders.pubscholar_v1: 开始爬取桶: qhash=335eaf85, total=266, max_page=6, filters={'lang': 'C', 'year': '2013', 'subject': '普通生物学', 'collection': '北大核心'}
2026-09-04 16:42:23 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:23 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:25 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
2026-09-04 16:42:25 [DEBUG] scrapy.core.engine: Crawled (404) <POST https://pubscholar.cn/hky/open/resources/api/v1/articles> (referer: https://pubscholar.cn/)
2026-09-04 16:42:28 [WARNING] scrapy.core.downloader.tls: Remote certificate is not valid for hostname "pubscholar.cn"; VerificationError(errors=[DNSMismatch(mismatched_id=DNS_ID(hostname=b'pubscholar.cn'))])
