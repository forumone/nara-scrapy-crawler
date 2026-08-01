import csv
import re

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class TrumpPetitionsSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "trump_petitions"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]

    SOURCE_SITE = 'petitions.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    # Output path is automatic, derived from SOURCE_SITE - pass -O <path> on
    # the CLI to override (Scrapy's -O/-o setting takes precedence over
    # custom_settings['FEEDS'], the same mechanism letsmove.py and
    # obama_whitehouse.py already use for their own output).
    custom_settings = {
        'FEEDS': {
            'data/petitions.trumpwhitehouse/petitions.trumpwhitehouse.csv': {
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

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/petitions.trumpwhitehouse/petitions.trumpwhitehouse_harvest.csv")
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
        if '/petition/' in response.url:
            yield from self._parse_petition(response)
        else:
            yield from self._parse_generic(response)

    def _parse_petition(self, response):
        warnings = []
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)

        date = re.sub(r'\s+', ' ', response.css('h4.petition-attribution::text').get(default='')).strip()
        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        full_text = f"{body} {date}".strip() if (date and any(c.isdigit() for c in date)) else body

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = full_text
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        yield item

    def _parse_generic(self, response):
        warnings = []
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)

        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            body = self._extract_text(response, '#content-main')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        yield item
