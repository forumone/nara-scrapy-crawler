import csv
import re

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, PRESS_RELEASE_LETTERHEAD_PATTERNS


class ClintonWhiteHouse4Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse4"
    allowed_domains = ["clintonwhitehouse4.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse4'
    SOURCE_TYPE = 'Archived White House Websites'

    # This template prepends a letter-spaced "T H E W H I T E H O U S E"
    # banner plus the page title and nav links to the body text on ~90% of
    # pages. The nav links appear as "Help Site Map", "Text Only Help Site
    # Map", or "Help Site Map Text Only" depending on the page - order and
    # presence of "Text Only" both vary. Strip through whichever form
    # appears, keeping only what follows it. The remaining pages use the
    # plain press-release letterhead instead, handled by the shared pattern
    # set appended below.
    LEADING_TEXT_STRIP_PATTERNS = (
        re.compile(
            r'^\s*T\s*H\s*E\s+W\s*H\s*I\s*T\s*E\s+H\s*O\s*U\s*S\s*E\b'
            r'.*?\b(?:Text\s+Only\s+)?Help\s+Site\s+Map(?:\s+Text\s+Only)?\b\s*',
            re.IGNORECASE,
        ),
    ) + PRESS_RELEASE_LETTERHEAD_PATTERNS

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse4/clintonwhitehouse4_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                # /textonly/ is a text-only mirror (11k of 25k URLs).
                # /OMB-upper/ and /omb-lower/ are alias prefixes for the canonical /OMB/ directory
                # (1969 paths each, both mapping to uppercase /OMB/). 1932/1969 have a scraped
                # /OMB/ counterpart; the 37 exceptions are paygo pages also excluded from /OMB/
                # at parse time (no_title).
                if '/textonly/' in url:
                    self._log_exclusion(url, 'url_pattern:/textonly/')
                elif '/OMB-upper/' in url:
                    self._log_exclusion(url, 'url_pattern:/OMB-upper/')
                elif '/omb-lower/' in url:
                    self._log_exclusion(url, 'url_pattern:/omb-lower/')
                else:
                    yield self._make_request(url)

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        # 1990s static HTML — WH press releases use <blockquote> for content;
        # non-briefing pages (OMB, CEQ, etc.) fall back to full body.
        body = (
            self._extract_text(response, 'blockquote')
            or self._extract_text(response, 'body')
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
