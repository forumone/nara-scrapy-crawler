import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class BidenWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "bidenwhitehouse"
    allowed_domains = ["bidenwhitehouse.archives.gov"]

    SOURCE_SITE = 'www.bidenwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/www.bidenwhitehouse/bidenwhitehouse_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        if response.css('frameset'):
            self._log_exclusion(response.url, 'frameset')
            return
        # WordPress site — standard .entry-content post body.
        # Some non-post pages (e.g. office landing pages) use .body-content instead.
        body = (
            self._extract_text(response, '.entry-content')
            or self._extract_text(response, '.body-content')
        )
        if not body:
            self._log_exclusion(response.url, 'no_body')
            return
        title = self._extract_title(response)
        if not title:
            self._log_exclusion(response.url, 'no_title')
            return
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
