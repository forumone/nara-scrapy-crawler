import csv
import re
from urllib.parse import urlparse

from scrapy.selector import Selector
from w3lib.html import remove_tags_with_content


# Explicit allowlist rather than a deny list: anything not in here (and not
# extension-free) is treated as a non-page asset and skipped.
_WEB_EXTENSIONS = frozenset({'html', 'htm', 'php', 'asp', 'aspx', 'shtml', 'cfm', 'cgi'})


def _is_web_url(url):
    """Return True if the URL looks like a web page rather than a downloadable asset.

    Rules, applied in order:
    1. No dot in the last path segment → no extension → allow (e.g. /about/page).
    2. "Extension" longer than 4 characters → not a real extension → allow
       (e.g. /page.xhtml; common asset extensions are 2–4 chars: .js, .pdf, .docx).
    3. Extension is in _WEB_EXTENSIONS → allow.
    4. Anything else (e.g. .pdf, .txt, .csv, .png) → deny.
    """
    path = urlparse(url).path.rstrip('/')
    last_segment = path.rsplit('/', 1)[-1] if path else ''
    if '.' not in last_segment:
        return True
    ext = last_segment.rsplit('.', 1)[-1].lower()
    return len(ext) > 4 or ext in _WEB_EXTENSIONS


class NavHarvesterMixin:
    r"""Mixin for CrawlSpider-based nav harvesters.

    Provides listing-file exclusion, web-page URL filtering, and a parse_nav
    callback. Subclasses supply name, allowed_domains, start_urls, and rules.

    See HARVESTING.md for the full end-to-end process this mixin fits into.

    listing_file is required
    ------------------------
    Every nav harvester must be given the output of its companion
    *_harvest_list spider via -a listing_file=<path>. This is not optional.

    The listing file provides URL-based pre-filtering: known listing-page URLs
    are loaded into _listing_urls at startup and checked before any request is
    made. A URL in that set is never fetched, never emitted, and its links are
    never followed. This is the definitive mechanism for keeping listing content
    out of the nav harvest.

    CSS-based listing detection (overriding _is_listing_page to inspect the
    response body) is intentionally not used in split harvesters. In-page
    signals such as .views-row are unreliable: content pages that embed a
    "More Like This" block carry the same markup as listing pages and would be
    incorrectly excluded. URL-based pre-filtering avoids this class of error
    entirely by relying on what the list harvester actually found rather than
    on assumptions about page structure.

    If a site is simple enough that a listing_file is unnecessary, it does not
    need a split harvester — use generic_crawl_harvest instead.

    Usage:
        # Step 1: run the list harvester first
        #   scrapy crawl mysite_harvest_list -o data/mysite_harvest_list.csv
        #
        # Step 2: feed its output to the nav harvester
        #   scrapy crawl mysite_harvest_nav \
        #       -a listing_file=data/mysite_harvest_list.csv \
        #       -o data/mysite_harvest_nav.csv

        class MySiteHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
            name = "mysite_harvest_nav"
            allowed_domains = ["example.com"]
            start_urls = [...]
            rules = (
                Rule(
                    # Use allow= to anchor to the exact hostname. allow_domains
                    # alone also matches subdomains, which are typically handled
                    # by their own separate spider.
                    LinkExtractor(
                        allow=r'//example\.com/',
                        allow_domains=['example.com'],
                    ),
                    callback='parse_nav',
                    follow=False,  # links followed manually in parse_nav
                ),
            )
    """

    # Subclasses that need a different depth can override custom_settings entirely.
    custom_settings = {
        'DEPTH_LIMIT': 2,
    }

    def __init__(self, listing_file=None, *args, **kwargs):
        if not listing_file:
            raise ValueError(
                "listing_file is required. Run the companion *_harvest_list spider "
                "first, then pass its output: -a listing_file=data/mysite_harvest_list.csv"
            )
        super().__init__(*args, **kwargs)
        self._listing_urls = set()
        with open(listing_file, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                self._listing_urls.add(row['url'])

    def _filter_web_urls(self, links):
        return [lnk for lnk in links if _is_web_url(lnk.url)]

    def _is_listing_page(self, response):
        """Return True if this response is a listing page that should be skipped.

        Default implementation checks only _listing_urls (populated from
        listing_file). Subclasses add site-specific detection — for example,
        checking for .views-row on sites where that selector reliably identifies
        listing pages and does not appear on content pages with embedded views.
        """
        return response.url in self._listing_urls

    def parse_nav(self, response):
        """Yield the URL and follow links if this is a nav content page.

        Listing pages are dropped entirely — no item yielded and no links
        followed. This prevents the spider from fanning out into listing
        sections and their thousands of content URLs.

        Links are followed manually (rather than via follow=True in the Rule)
        so that we can gate following on this per-page check. Subclass rules
        must set follow=False and omit process_links; filtering is applied here.

        The web-URL guard is applied to response.url as well as to extracted
        links because CrawlSpider's Rule dispatches links directly to this
        callback before _filter_web_urls has a chance to screen them.
        """
        if not _is_web_url(response.url):
            return
        if self._is_listing_page(response):
            return
        yield {'url': response.url}
        for rule in self._rules:
            links = self._filter_web_urls(rule.link_extractor.extract_links(response))
            for link in links:
                yield response.follow(link.url, callback=self.parse_nav)


class ArchiveSpiderMixin:
    # min_offset: skip N chars before searching for a sentence boundary, avoiding
    #   false splits on abbreviations like "Mr." or "U.S." (default: 60)
    # max_len: hard character cap on the result (default: 200)
    # truncate_after: cut at the first space after max_len rather than the last
    #   space before it (default: False — trim before the boundary)
    # ellipsis: append "…" to truncated results (default: True)
    @staticmethod
    def _teaser(text, min_offset=60, max_len=200, truncate_after=False, ellipsis=True):
        if not text:
            return ''
        m = re.search(r'[.!?](?=\s+[A-Z])', text[min_offset:])
        result = text[:min_offset + m.end()] if m else text
        suffix = '…' if ellipsis else ''
        if len(result) <= max_len:
            return result + suffix
        if truncate_after:
            next_space = result.find(' ', max_len)
            truncated = result[:next_space] if next_space != -1 else result
        else:
            truncated_raw = result[:max_len]
            last_space = truncated_raw.rfind(' ')
            truncated = truncated_raw[:last_space] if last_space > 0 else truncated_raw
        return truncated + suffix

    def _extract_text(self, response, selector):
        match = response.css(selector).get()
        if not match:
            return ''
        try:
            cleaned = remove_tags_with_content(match, which_ones=('script', 'style'))
        except TypeError:
            cleaned = ''
        text = Selector(text=cleaned).xpath('string(.)').get(default='')
        return re.sub(r'\s+', ' ', text).strip()
