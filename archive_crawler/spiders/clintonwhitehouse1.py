import csv

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, PRESS_RELEASE_LETTERHEAD_PATTERNS


class ClintonWhiteHouse1Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse1"
    allowed_domains = ["clintonwhitehouse1.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse1'
    SOURCE_TYPE = 'Archived White House Websites'

    LEADING_TEXT_STRIP_PATTERNS = PRESS_RELEASE_LETTERHEAD_PATTERNS

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse1/clintonwhitehouse1_harvest-full.csv"
            )
        rules = self._get_exclusion_rules()
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                reason = exclusion_rules.match_exclude(url, rules)
                if reason:
                    self._log_exclusion(url, reason)
                else:
                    yield self._make_request(url)

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        body = self._extract_press_release_body(response)
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
