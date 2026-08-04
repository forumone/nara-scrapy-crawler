import re

import scrapy

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import SitemapUrlSpiderMixin, TEXT_VERSION_TOGGLE_PATTERNS, omb_paygo_title


class ClintonWhiteHouse4Spider(SitemapUrlSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse4"
    allowed_domains = ["clintonwhitehouse4.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse4'
    SOURCE_TYPE = 'Archived White House Websites'

    SITEMAP_URL = 'https://clintonwhitehouse4.archives.gov/sitemap.xml'

    custom_settings = {
        'FEEDS': {
            'data/clintonwhitehouse4/clintonwhitehouse4_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url'],
            },
            'data/clintonwhitehouse4/clintonwhitehouse4.csv': {
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

    # This template prepends a letter-spaced "T H E W H I T E H O U S E"
    # banner plus the page title and nav links to the body text on ~90% of
    # pages. The nav links appear as "Help Site Map", "Text Only Help Site
    # Map", or "Help Site Map Text Only" depending on the page - order and
    # presence of "Text Only" both vary. Strip through whichever form
    # appears, keeping only what follows it - this is nav chrome, stripped
    # regardless of the letterhead-content policy below. The remaining pages
    # use the plain press-release letterhead instead - no longer stripped,
    # see TEXT_VERSION_TOGGLE_PATTERNS.
    LEADING_TEXT_STRIP_PATTERNS = (
        re.compile(
            r'^\s*T\s*H\s*E\s+W\s*H\s*I\s*T\s*E\s+H\s*O\s*U\s*S\s*E\b'
            r'.*?\b(?:Text\s+Only\s+)?Help\s+Site\s+Map(?:\s+Text\s+Only)?\b\s*',
            re.IGNORECASE,
        ),
    ) + TEXT_VERSION_TOGGLE_PATTERNS

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
            title = omb_paygo_title(body)
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
