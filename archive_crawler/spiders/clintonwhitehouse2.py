import csv

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, TEXT_VERSION_TOGGLE_PATTERNS


class ClintonWhiteHouse2Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse2"
    allowed_domains = ["clintonwhitehouse2.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse2'
    SOURCE_TYPE = 'Archived White House Websites'

    # Output path is automatic, derived from SOURCE_SITE - pass -O <path> on
    # the CLI to override (Scrapy's -O/-o setting takes precedence over
    # custom_settings['FEEDS'], same mechanism already used by the fused
    # nav-harvest spiders).
    custom_settings = {
        'FEEDS': {
            'data/clintonwhitehouse2/clintonwhitehouse2.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [ArchiveItem],
                'fields': [
                    'url', 'title', 'teaser_text', 'full_text',
                    'source_site', 'source_type', 'warnings',
                ],
            },
        },
    }

    LEADING_TEXT_STRIP_PATTERNS = TEXT_VERSION_TOGGLE_PATTERNS

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv"
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
        warnings = []
        body = self._extract_press_release_body(response)
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = self._extract_title(response)
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        yield item
