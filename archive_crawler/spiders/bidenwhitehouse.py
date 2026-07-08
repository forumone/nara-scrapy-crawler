import csv
import re

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class BidenWhiteHouseSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "bidenwhitehouse"
    allowed_domains = ["bidenwhitehouse.archives.gov"]

    SOURCE_SITE = 'www.bidenwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    # Presidential bio pages (/about-the-white-house/presidents/*) embed the
    # full nav list of all U.S. presidents ahead of the actual bio text.
    # Strip through the last name in that list, kept fixed since these are
    # frozen archive snapshots.
    LEADING_TEXT_STRIP_PATTERNS = (
        re.compile(
            r'^\s*Presidents\s+George\s+Washington\b.*?\bJoseph\s+R\.\s+Biden\s+Jr\.\s*',
            re.IGNORECASE,
        ),
    )

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/www.bidenwhitehouse/bidenwhitehouse_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                yield self._make_request(row['url'])

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        # WordPress site — standard .entry-content post body.
        # Some non-post pages (e.g. office landing pages) use .body-content instead.
        body = (
            self._extract_text(response, '.entry-content')
            or self._extract_text(response, '.body-content')
        )
        if not body:
            self._log_exclusion(response.url, 'no_body')
            return
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
