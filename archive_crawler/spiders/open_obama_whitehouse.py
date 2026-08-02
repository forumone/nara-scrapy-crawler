import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class OpenSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "open_obama_whitehouse"
    allowed_domains = ["open.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'open.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        if 'dataset' in response.url:
            yield from self._parse_dataset(response)
        else:
            yield from self._parse_generic(response)

    def _parse_dataset(self, response):
        warnings = []
        body = self._extract_text(response, 'div.field-name-body div.field-items')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = response.xpath(
            "normalize-space(//div[contains(@class, 'radix-layouts-content')]//h2[@class='pane-title']/text())"
        ).get(default='').strip()
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

    def _parse_generic(self, response):
        # Non-dataset pages (homepage, group pages, etc.) are navigation/listing
        # pages with no extractable article content, by design - always tagged
        # no_body (never short_body, since body is always empty here, never
        # just short) rather than conditionally checked like the standard
        # paradigm. Yield with empty full_text so the page is findable by
        # title in search without polluting full_text with page chrome.
        title = response.xpath('//title/text()').get(default='').strip()
        warnings = ['no_body']
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = ''
        item['teaser_text'] = ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        yield item
