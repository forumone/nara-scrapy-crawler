import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class LetsMoveSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "letsmove"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'letsmove.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/letsmove.obamawhitehouse/letsmove_harvest_full.csv")
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        body = self._extract_text(response, '#maincontent .node .content')
        if not body:
            return

        title = response.css('#maincontent h1').xpath('string(.)').get(default='').strip()
        if not title:
            return

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
