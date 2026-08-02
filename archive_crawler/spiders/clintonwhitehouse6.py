import csv
import re
from urllib.parse import urlparse

import scrapy

from archive_crawler import exclusion_rules
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, TEXT_VERSION_TOGGLE_PATTERNS


def _title_from_slug(url):
    """Derive a human-readable title from a CW6 URL slug.

    CW6 pages have empty <title> tags. Filenames follow the pattern
    YYYY-MM-DD-title-words-here.html; strip the date prefix and un-hyphenate.
    """
    stem = urlparse(url).path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    stem = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', stem)
    return stem.replace('-', ' ').title() if stem else ''


class ClintonWhiteHouse6Spider(ArchiveSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse6"
    allowed_domains = ["clintonwhitehouse6.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse6'
    SOURCE_TYPE = 'Archived White House Websites'

    # Output path is automatic, derived from SOURCE_SITE - pass -O <path> on
    # the CLI to override (Scrapy's -O/-o setting takes precedence over
    # custom_settings['FEEDS'], the same mechanism letsmove.py and
    # obama_whitehouse.py already use for their own output).
    custom_settings = {
        'FEEDS': {
            'data/clintonwhitehouse6/clintonwhitehouse6.csv': {
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

    # Each CW6 page has a "View Header" link pointing to its companion .header.html
    # file. Strip it so the link text doesn't appear at the start of every full_text.
    EXTRA_STRIP_SELECTORS = ('a[href$=".header.html"]',)

    LEADING_TEXT_STRIP_PATTERNS = TEXT_VERSION_TOGGLE_PATTERNS

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse6/clintonwhitehouse6_harvest-full.csv"
            )
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
        warnings = []
        # CW6 pages have no <blockquote> wrapper and empty <title> tags.
        # Content is paragraphs directly in <body> beneath nav divs (#menufloat, #frozen-spacer).
        body = self._extract_text(response, 'body')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        # h1/h2 not present on any inspected pages; title tag is populated on index pages
        # but empty on dated documents; slug derivation handles the dated-document case.
        title = self._extract_title(response) or _title_from_slug(response.url)
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
