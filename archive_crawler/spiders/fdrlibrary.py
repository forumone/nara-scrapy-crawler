import html
import re

import scrapy

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import SitemapUrlSpiderMixin


class FDRLibrarySpider(SitemapUrlSpiderMixin, scrapy.Spider):
    """FDR Presidential Library & Museum (www.fdrlibrary.org).

    This site is a live Liferay Portal 6.2 install that its owners still
    maintain, not a frozen archive snapshot. The client has no access to
    the site, so a crawl is the only way to index it. The selectors below
    match the current Liferay theme. A site upgrade or redesign will
    probably break them."""

    name = "fdrlibrary"
    allowed_domains = ["www.fdrlibrary.org"]

    SOURCE_SITE = 'www.fdrlibrary'
    # Placeholder until the TL confirms a value for this site. The FDR
    # Library is not an archived White House site.
    SOURCE_TYPE = 'Archived White House Websites'

    SITEMAP_URL = 'https://www.fdrlibrary.org/sitemap.xml'

    _TITLE_SUFFIX_RE = re.compile(r'\s*-\s*FDR Presidential Library & Museum\s*$')

    custom_settings = {
        # A live production server, so a gentler default than settings.py.
        # --download-delay / --concurrent-requests-per-domain still override.
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'FEEDS': {
            'data/www.fdrlibrary/www.fdrlibrary_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url'],
            },
            'data/www.fdrlibrary/www.fdrlibrary.csv': {
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

    def _extract_body(self, response):
        # Each page is a set of Liferay "Web Content Display" portlets, one
        # .journal-content-article each, in a layout that varies per page.
        # Join every article inside <main id="main-content">, in document
        # order. This skips the header "Museum Hours" article and the
        # Navigation portlets, which hold no .journal-content-article.
        articles = response.xpath(
            '//main[@id="main-content"]'
            '//div[contains(concat(" ", normalize-space(@class), " "), " journal-content-article ")]'
        ).getall()
        texts = (self._clean_matched_html(a) for a in articles)
        return ' '.join(t for t in texts if t)

    def _extract_fdr_title(self, response):
        # Every <h1> on this theme is a Liferay portlet title ("Web Content
        # Display", "Navigation"), so _extract_title's h1/h2 pass returns
        # junk. <title> holds the real page title plus a fixed site suffix.
        raw = response.css('title::text').get(default='')
        title = html.unescape(re.sub(r'\s+', ' ', raw)).strip()
        return self._TITLE_SUFFIX_RE.sub('', title)

    def parse_item(self, response):
        if self._is_excluded_response(response):
            return
        warnings = []
        body = self._extract_body(response)
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = self._extract_fdr_title(response)
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
