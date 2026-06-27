import csv

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class GeorgeWBushWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "georgewbush_whitehouse"
    allowed_domains = ["georgewbush-whitehouse.archives.gov"]

    SOURCE_SITE = 'www.georgewbush-whitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/www.georgewbush-whitehouse/georgewbush-whitehouse_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                # /images/ subdirectory pages are photo gallery wrappers with no text (28k URLs).
                # .v.html pages are video transcript variants (11k URLs); skip to avoid duplicates.
                # /print/ subdirectories are printer-friendly duplicates of main content (68k URLs).
                # /text/ subdirectories are plain-text duplicates of main content (94k URLs).
                # .es.html pages are Spanish-language variants.
                if '/images/' in url:
                    self._log_exclusion(url, 'url_pattern:/images/')
                elif url.endswith('.v.html'):
                    self._log_exclusion(url, 'url_pattern:.v.html')
                elif '/print/' in url:
                    self._log_exclusion(url, 'url_pattern:/print/')
                elif '/text/' in url:
                    self._log_exclusion(url, 'url_pattern:/text/')
                elif url.endswith('.es.html'):
                    self._log_exclusion(url, 'url_pattern:.es.html')
                else:
                    yield self._make_request(url)

    def parse_item(self, response):
        if response.css('frameset'):
            self._log_exclusion(response.url, 'frameset')
            return
        # Selector chain across three distinct sub-site layouts on this archive:
        # 1. #news_container — main WH press release layout (inside #whitebox).
        # 2. #whitebox — speeches/remarks on a slightly different WH template.
        # 3. #mainContent — OMB E-Gov sub-site (/omb/) with its own layout.
        # 4. font.BDYpixel — results.gov biographical content (/results/, /v/);
        #    old font-tag layout with no semantic container IDs.
        body = (
            self._extract_text(response, '#news_container')
            or self._extract_text(response, '#whitebox')
            or self._extract_text(response, '#mainContent')
            or self._extract_text(response, 'font.BDYpixel')
        )
        if not body:
            self._log_exclusion(response.url, 'no_body')
            return
        # No h1 on most pages; <title> tag matches the bolded article heading.
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
