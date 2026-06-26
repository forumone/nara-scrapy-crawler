import logging
import os
from datetime import datetime

from scrapy import signals


class ErrorFileLogger:
    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        return ext

    def spider_opened(self, spider):
        source_site = getattr(spider, 'SOURCE_SITE', None)
        data_dir = f'data/{source_site}' if source_site else 'data'
        os.makedirs(data_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        handler = logging.FileHandler(f'{data_dir}/{spider.name}-errors-{timestamp}.log')
        handler.setLevel(logging.ERROR)
        logging.getLogger('scrapy').addHandler(handler)
