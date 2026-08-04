import scrapy

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import SitemapUrlSpiderMixin, TEXT_VERSION_TOGGLE_PATTERNS


class ClintonWhiteHouse2Spider(SitemapUrlSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse2"
    allowed_domains = ["clintonwhitehouse2.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse2'
    SOURCE_TYPE = 'Archived White House Websites'

    SITEMAP_URL = 'https://clintonwhitehouse2.archives.gov/sitemap.xml'

    custom_settings = {
        'FEEDS': {
            'data/clintonwhitehouse2/clintonwhitehouse2_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url'],
            },
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
