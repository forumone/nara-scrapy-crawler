import csv
import re
from urllib.parse import urlparse

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


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

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                "-a url_file=data/clintonwhitehouse6/clintonwhitehouse6_harvest-full.csv"
            )
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                # .header.html files are companion header fragments, not content (20k of 40k URLs).
                if url.endswith('.header.html'):
                    continue
                yield scrapy.Request(url, callback=self.parse_item)

    def parse_item(self, response):
        # CW6 pages have no <blockquote> wrapper and empty <title> tags.
        # Content is paragraphs directly in <body> beneath nav divs (#menufloat, #frozen-spacer).
        body = self._extract_text(response, 'body')
        if not body:
            return
        # h1/h2 not present on any inspected pages; title tag is populated on index pages
        # but empty on dated documents; slug derivation handles the dated-document case.
        title = self._extract_title(response) or _title_from_slug(response.url)
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
