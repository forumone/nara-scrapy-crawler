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

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        warnings = []
        # WordPress site — standard .entry-content post body.
        # Some non-post pages (e.g. office landing pages) use .body-content instead.
        body = (
            self._extract_text(response, '.entry-content')
            or self._extract_text(response, '.body-content')
        )
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
