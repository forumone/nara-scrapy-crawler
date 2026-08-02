import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import UrlFileSpiderMixin, TEXT_VERSION_TOGGLE_PATTERNS


class ClintonWhiteHouse1Spider(UrlFileSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse1"
    allowed_domains = ["clintonwhitehouse1.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse1'
    SOURCE_TYPE = 'Archived White House Websites'

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
