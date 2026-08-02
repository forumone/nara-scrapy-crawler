import re
from urllib.parse import urlparse

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import UrlFileSpiderMixin, TEXT_VERSION_TOGGLE_PATTERNS


def _title_from_slug(url):
    """Derive a human-readable title from a CW6 URL slug.

    CW6 pages have empty <title> tags. Filenames follow the pattern
    YYYY-MM-DD-title-words-here.html; strip the date prefix and un-hyphenate.
    """
    stem = urlparse(url).path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    stem = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', stem)
    return stem.replace('-', ' ').title() if stem else ''


class ClintonWhiteHouse6Spider(UrlFileSpiderMixin, scrapy.Spider):
    name = "clintonwhitehouse6"
    allowed_domains = ["clintonwhitehouse6.archives.gov"]

    SOURCE_SITE = 'clintonwhitehouse6'
    SOURCE_TYPE = 'Archived White House Websites'

    # Each CW6 page has a "View Header" link pointing to its companion .header.html
    # file. Strip it so the link text doesn't appear at the start of every full_text.
    EXTRA_STRIP_SELECTORS = ('a[href$=".header.html"]',)

    LEADING_TEXT_STRIP_PATTERNS = TEXT_VERSION_TOGGLE_PATTERNS

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
