import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class ClintonWhiteHouse2Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse2"
    allowed_domains = ["clintonwhitehouse2.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse2'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        # 1990s static HTML — WH press releases use <blockquote> for content;
        # non-briefing pages (OMB, CEQ, etc.) fall back to full body.
        body = (
            self._extract_text(response, 'blockquote')
            or self._extract_text(response, 'body')
        )
        if not body:
            return
        title = self._extract_title(response)
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
