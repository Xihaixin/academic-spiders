"""
简洁日志格式化器: 只记录关键内容, 不打印完整 Item

Scrapy 默认 LogFormatter 在 DEBUG 级别会打印完整 item dict
(含 abstracts 全文、authors 机构数组等), 单条可达数 KB。
而完整 JSON 数据已由 JsonExportPipeline 保存到 output/ 目录,
日志中重复输出会导致:
  1. 日志文件急剧膨胀 (50 条/页 × 全量页数)
  2. 海量数据行淹没关键运行信息 (翻页进度、错误、限流等)

本类重写 scraped(): 每条文献只记一行摘要 (页码/标题/去重键)。
其余消息 (Crawled / Retry / 错误) 保持 Scrapy 默认格式不变。
"""

import logging

from scrapy import logformatter

# 标题最大显示长度 (超出截断, 日志只需要能辨认是哪篇即可)
_TITLE_MAX_LEN = 60


class ConciseLogFormatter(logformatter.LogFormatter):
    """Item 只记一行摘要, 其余日志格式保持 Scrapy 默认"""

    def scraped(self, item, response, spider):
        title = (item.get("title") or "").strip() or "(无标题)"
        if len(title) > _TITLE_MAX_LEN:
            title = title[:_TITLE_MAX_LEN] + "…"
        return {
            "level": logging.DEBUG,
            "msg": "第 %(page)s 页 文献: title=%(title)s, "
                   "dedup_key=%(dedup)s",
            "args": {
                "page": item.get("_page", "?"),
                "title": title,
                "dedup": item.get("dedup_key") or "-",
            },
        }
