import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, PRESS_RELEASE_LETTERHEAD_PATTERNS


class ClintonWhiteHouse2Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse2"
    allowed_domains = ["clintonwhitehouse2.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse2'
    SOURCE_TYPE = 'Archived White House Websites'

    LEADING_TEXT_STRIP_PATTERNS = PRESS_RELEASE_LETTERHEAD_PATTERNS

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield self._make_request(row['url'])

    def parse_item(self, response):
        if self._is_excluded_response(response):
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
