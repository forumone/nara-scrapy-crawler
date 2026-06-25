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
        os.makedirs('data', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        handler = logging.FileHandler(f'data/{spider.name}-errors-{timestamp}.log')
        handler.setLevel(logging.ERROR)
        logging.getLogger('scrapy').addHandler(handler)
