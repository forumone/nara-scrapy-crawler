import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class ObamaWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "obama_whitehouse"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'www.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv")
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        if response.css('.views-row'):
            return
        body = (self._extract_text(response, '.field-items .field-item') or
                self._extract_text(response, '.longpage-sections'))
        if not body:
            return
        title = response.css('h1').xpath('string(.)').get(default='').strip()
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
