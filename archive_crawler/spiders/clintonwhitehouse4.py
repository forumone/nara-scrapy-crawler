import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class ClintonWhiteHouse4Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse4"
    allowed_domains = ["clintonwhitehouse4.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse4'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse4_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                url = row['url']
                # /textonly/ is a text-only mirror (11k of 25k URLs).
                # /OMB-upper/ and /omb-lower/ are 100% identical to /OMB/ (1969 paths each).
                if '/textonly/' in url or '/OMB-upper/' in url or '/omb-lower/' in url:
                    continue
                yield scrapy.Request(url, callback=self.parse_item)

    def parse_item(self, response):
        # 1990s static HTML — WH press releases use <blockquote> for content;
        # non-briefing pages (OMB, CEQ, etc.) fall back to full body.
        body = (
            self._extract_text(response, 'blockquote')
            or self._extract_text(response, 'body')
        )
        if not body:
            return
        title = (
            response.css('h1').xpath('string(.)').get(default='').strip()
            or response.css('h2').xpath('string(.)').get(default='').strip()
            or response.css('title::text').get(default='').strip()
        )
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
