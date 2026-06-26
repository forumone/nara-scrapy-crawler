import csv
import re

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class TrumpPetitionsSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "trump_petitions"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]

    SOURCE_SITE = 'petitions.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/petitions.trumpwhitehouse/petitions.trumpwhitehouse_harvest.csv")
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        if '/petition/' in response.url:
            yield from self._parse_petition(response)
        else:
            yield from self._parse_generic(response)

    def _parse_petition(self, response):
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            return

        date = re.sub(r'\s+', ' ', response.css('h4.petition-attribution::text').get(default='')).strip()
        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        full_text = f"{body} {date}".strip() if (date and any(c.isdigit() for c in date)) else body

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = full_text
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def _parse_generic(self, response):
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            return

        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            body = self._extract_text(response, '#content-main')

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
