import csv
import html
import os
import re
from urllib.parse import urlparse

import scrapy
from scrapy.selector import Selector
from w3lib.html import remove_tags, remove_tags_with_content

# Invisible Unicode format characters that appear in archived source HTML.
# Soft hyphen (U+00AD), zero-width space/non-joiner/joiner (U+200B-D),
# directional marks (U+200E-F), BOM/ZWNBSP (U+FEFF).
_INVISIBLE_RE = re.compile('[\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]')


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
        with open(listing_file, newline='', encoding='utf-8-sig') as f:
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
    # CSS selectors for site-specific boilerplate to strip before text extraction,
    # in addition to the shared selectors (#menufloat, .mobile-select, etc.).
    # Override in subclasses, e.g.: EXTRA_STRIP_SELECTORS = ('a[href$=".header.html"]',)
    EXTRA_STRIP_SELECTORS = ()

    # XPath expressions for boilerplate that can't be expressed as CSS selectors
    # (e.g. parent-of conditions). Applied in the same pre-extraction pass as
    # EXTRA_STRIP_SELECTORS. Each expression is evaluated against the full document.
    # Override in subclasses, e.g.:
    #   EXTRA_STRIP_XPATH = ('.//center[.//img[@src="/911/images/star.gif"]]',)
    EXTRA_STRIP_XPATH = ()

    # max_len: hard character cap (default: 200)
    # truncate_after: cut at the first space after max_len rather than the last
    #   space before it (default: False — trim before the boundary)
    # ellipsis: append "…" to truncated results (default: True)
    @staticmethod
    def _teaser(text, max_len=200, truncate_after=False, ellipsis=True):
        if not text:
            return ''
        # Strip repeated-punctuation runs (separators like "________" or "********").
        text = re.sub(r'([\W_])\1{2,} ?', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= max_len:
            return text
        if truncate_after:
            next_space = text.find(' ', max_len)
            output = text[:next_space] if next_space != -1 else text[:max_len]
        else:
            last_space = text[:max_len].rfind(' ')
            output = text[:last_space] if last_space > 0 else text[:max_len]
        if not ellipsis:
            return output
        if output.endswith('.'):
            return output + ' …'
        return output + '…'

    @staticmethod
    def _extract_title(response):
        """Return the best available title for a page.

        Tries h1, h2, then <title> in order. The <title> fallback strips any
        embedded HTML tags — 1990s archived pages sometimes store markup like
        <font> or <b> as literal text inside <title> elements, which an HTML
        parser surfaces verbatim via ::text.
        """
        title = (
            response.css('h1').xpath('string(.)').get(default='').strip()
            or response.css('h2').xpath('string(.)').get(default='').strip()
        )
        if not title:
            raw = response.css('title::text').get(default='').strip()
            title = remove_tags(raw)
        title = re.sub(r'([\W_])\1{2,}', '', title)
        title = html.unescape(title)
        title = _INVISIBLE_RE.sub('', title)
        return re.sub(r'\s+', ' ', title).strip()

    def _make_request(self, url, **kwargs):
        kwargs.setdefault('callback', self.parse_item)
        kwargs.setdefault('errback', self._log_http_error)
        return scrapy.Request(url, **kwargs)

    def _log_http_error(self, failure):
        from scrapy.spidermiddlewares.httperror import HttpError
        if failure.check(HttpError):
            status = failure.value.response.status
            if status < 400:
                reason = 'http_3xx'
            elif status >= 500:
                reason = 'http_5xx'
            else:
                reason = f'http_{status}'
            self._log_exclusion(failure.value.response.url, reason)
        else:
            self._log_exclusion(failure.request.url, f'network_error:{failure.type.__name__}')

    def _log_exclusion(self, url, reason):
        if not hasattr(self, '_exclusions'):
            self._exclusions = []
        self._exclusions.append({'url': url, 'reason': reason})

    def closed(self, reason):
        exclusions = getattr(self, '_exclusions', [])
        if not exclusions:
            return
        out_dir = os.path.join('data', self.SOURCE_SITE)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'{self.SOURCE_SITE}_exclusions.csv')
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'reason'])
            writer.writeheader()
            writer.writerows(exclusions)

    def _extract_text(self, response, selector):
        if response.css('frameset'):
            return ''
        # XPath expressions start with // or .//; everything else is CSS.
        if selector.startswith('//') or selector.startswith('.//'):
            match = response.xpath(selector).get()
        else:
            match = response.css(selector).get()
        if not match:
            return ''
        try:
            cleaned = remove_tags_with_content(match, which_ones=('script', 'style'))
        except TypeError:
            cleaned = ''
        # Remove injected/boilerplate UI elements BEFORE the </div>→space
        # substitution below. If we wait until after, the </div> on #menufloat
        # is replaced with a space, leaving it unclosed; lxml then re-parses and
        # nests all subsequent siblings inside #menufloat, so removing it would
        # silently delete all body content.
        # #menufloat: NARA's banner on Clinton-era archived sites.
        # .mobile-select: Biden WH mobile section-nav widget (hidden on desktop).
        # table[summary*="Breadcrumbs"], table[summary*="Print"]: breadcrumb/print
        #   navigation tables common on GWBush-era archived government sites.
        sel_pre = Selector(text=cleaned)
        boilerplate = '#menufloat, .mobile-select, table[summary*="Breadcrumbs"], table[summary*="Print"]'
        if self.EXTRA_STRIP_SELECTORS:
            boilerplate += ', ' + ', '.join(self.EXTRA_STRIP_SELECTORS)
        for node in sel_pre.css(boilerplate):
            parent = node.root.getparent()
            if parent is not None:
                parent.remove(node.root)
        for xpath_expr in self.EXTRA_STRIP_XPATH:
            for node in sel_pre.xpath(xpath_expr):
                parent = node.root.getparent()
                if parent is not None:
                    parent.remove(node.root)
        cleaned = sel_pre.css('body').get() or cleaned
        # Replace <br> and block-closing tags with a space before parsing so
        # that xpath string() doesn't merge adjacent words across line breaks.
        cleaned = re.sub(
            r'<br\s*/?>|</(?:p|div|li|td|th|tr|h[1-6]|blockquote|pre)\s*>',
            ' ', cleaned, flags=re.IGNORECASE,
        )
        sel = Selector(text=cleaned)
        text = sel.xpath('string(.)').get(default='')
        text = html.unescape(re.sub(r'\s+', ' ', text).strip())
        return _INVISIBLE_RE.sub('', text)
