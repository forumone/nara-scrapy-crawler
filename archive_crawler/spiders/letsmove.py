import csv

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class LetsMoveSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "letsmove"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'letsmove.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/letsmove.obamawhitehouse/letsmove_harvest_full.csv")
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
        body = self._extract_text(response, '#maincontent .node .content')
        if not body:
            self._log_exclusion(response.url, 'no_body')
            return
        title = response.css('#maincontent h1').xpath('string(.)').get(default='').strip()
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
