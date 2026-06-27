import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class ClintonWhiteHouse5Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse5"
    allowed_domains = ["clintonwhitehouse5.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse5'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse5/clintonwhitehouse5_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                # /textonly/ is a text-only mirror (11k of 26k URLs).
                # OMB dirs: OMB-upper (1984 URLs) = omb (1815) + OMB (169); OMB-bak ≈ OMB-upper.
                # Keep /OMB-upper/ as the most complete unique set; skip the rest.
                if '/textonly/' in url:
                    self._log_exclusion(url, 'url_pattern:/textonly/')
                elif '/omb/' in url:
                    self._log_exclusion(url, 'url_pattern:/omb/')
                elif '/OMB/' in url:
                    self._log_exclusion(url, 'url_pattern:/OMB/')
                elif '/OMB-bak/' in url:
                    self._log_exclusion(url, 'url_pattern:/OMB-bak/')
                else:
                    yield scrapy.Request(url, callback=self.parse_item)

    def parse_item(self, response):
        if response.css('frameset'):
            self._log_exclusion(response.url, 'frameset')
            return
        # 1990s static HTML — WH press releases use <blockquote> for content;
        # non-briefing pages (OMB, CEQ, etc.) fall back to full body.
        body = (
            self._extract_text(response, 'blockquote')
            or self._extract_text(response, 'body')
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
