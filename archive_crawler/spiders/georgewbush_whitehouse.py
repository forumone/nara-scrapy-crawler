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
                if '/images/' in url or url.endswith('.v.html') or '/print/' in url or '/text/' in url:
                    continue
                yield scrapy.Request(url, callback=self.parse_item)

    def parse_item(self, response):
        # Two-column layout: #leftcol is site navigation; #whitebox is the article area.
        # #news_container is a child of #whitebox that starts at the article text,
        # skipping the leading breadcrumb table and "For Immediate Release" block.
        # Fall back to #whitebox for pages that lack #news_container (speeches, remarks,
        # etc. on a slightly different template); those pages include breadcrumb boilerplate
        # at the top of #whitebox but the main content follows immediately after.
        body = (
            self._extract_text(response, '#news_container')
            or self._extract_text(response, '#whitebox')
        )
        if not body:
            return
        # No h1 on most pages; <title> tag matches the bolded article heading.
        title = self._extract_title(response)
        if not title:
            return
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
