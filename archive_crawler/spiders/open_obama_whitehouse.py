import csv

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class OpenSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "open_obama_whitehouse"
    allowed_domains = ["open.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'open.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/open.obamawhitehouse/open.obamawhitehouse_harvest.csv")
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
        if 'dataset' in response.url:
            yield from self._parse_dataset(response)
        else:
            yield from self._parse_generic(response)

    def _parse_dataset(self, response):
        body = self._extract_text(response, 'div.field-name-body div.field-items')
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.xpath(
            "normalize-space(//div[contains(@class, 'radix-layouts-content')]//h2[@class='pane-title']/text())"
        ).get(default='').strip()
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def _parse_generic(self, response):
        # Non-dataset pages (homepage, group pages, etc.) are navigation/listing
        # pages with no extractable article content. Yield with empty full_text so
        # the page is findable by title in search without polluting full_text with
        # page chrome.
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.xpath('//title/text()').get(default='').strip()
        item['full_text'] = ''
        item['teaser_text'] = ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
