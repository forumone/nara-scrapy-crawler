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

# Matches a single h1/h2 element and its content, non-greedy so it stops at
# the first closing tag encountered in the source, the same span lxml uses
# when deciding where the element ends.
_HEADING_SPAN_RE = re.compile(r'(<h[12]\b[^>]*>)(.*?)(</h[12]>)', re.IGNORECASE | re.DOTALL)
# Block-level tags that, when left unclosed inside a heading (e.g. archived
# pages that omit </p> in "<h1>Foo<p>Bar</h1>"), make lxml auto-close the
# still-open h1/h2 the moment it hits the nested tag, silently truncating
# the heading and stranding the rest as an orphan sibling no selector can
# recover. Stripping these tags out of the heading span before parsing keeps
# the heading text intact.
_NESTED_BLOCK_TAG_RE = re.compile(
    r'</?(?:p|div|table|ul|ol|li|center|blockquote|tr|td|th)\b[^>]*>', re.IGNORECASE,
)

_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August'
    r'|September|October|November|December)'
)
_WEEKDAYS = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'

# Shared press-release letterhead used by CW1-6 and GWBush (and appended
# after the CW4/CW5 nav-banner pattern for pages that use the plain
# letterhead instead). Components appear in varying combinations and order
# (e.g. GWBush puts "For Immediate Release" before "Office of the Press
# Secretary"), so these are meant to be applied in a fixpoint loop rather
# than a single pass - see _extract_text.
#
# The masthead only strips when immediately followed by a recognized
# continuation, never unconditionally, so it doesn't eat legitimate titles
# that happen to start with "The White House" (e.g. "The White House
# Visitors Office" or "The White House Conference on the New Economy").
PRESS_RELEASE_LETTERHEAD_PATTERNS = (
    re.compile(
        r'^\s*T\s*H\s*E\s+W\s*H\s*I\s*T\s*E\s+H\s*O\s*U\s*S\s*E\b\s*'
        r'(?=Office\s+of\s+the\s+(?:Press\s+Secretary|Vice\s+President)\b'
        r'|AT\s+WORK\b'
        r'|For\s+Immediate\s+Release\b'
        r'|Washington\b'
        r'|\('
        r'|' + _MONTHS + r'\s+\d{1,2}\b'
        r')',
        re.IGNORECASE,
    ),
    re.compile(r'^\s*Office\s+of\s+the\s+Press\s+Secretary\b\s*', re.IGNORECASE),
    re.compile(r'^\s*\([A-Za-z .,\'’-]{2,80}\)\s*'),
    re.compile(r'^\s*For\s+Immediate\s+Release\b\s*:?\s*', re.IGNORECASE),
    re.compile(r'^\s*posted\s+by:?\s*The\s+White\s+House\b\s*', re.IGNORECASE),
    re.compile(r'^\s*Contact:?\s*[\d\-() ]{7,20}\s*', re.IGNORECASE),
    re.compile(r'^\s*' + _WEEKDAYS + r',?\s+' + _MONTHS + r'\s+\d{1,2},?\s*\d{4}\s*', re.IGNORECASE),
    re.compile(r'^\s*' + _MONTHS + r'\s+\d{1,2},?\s*\d{4}\s*', re.IGNORECASE),
)

# Clinton-era press-release pages (CW1-5) often have the masthead as its own
# h1/h2 ("THE WHITE HOUSE" or "THE WHITE HOUSE Office of the Press
# Secretary") followed by a second heading with the real subject; _extract_title
# only ever reads the first heading, so it picks up the masthead instead of
# the title. Matches only when the ENTIRE heading text is masthead
# (+ optional office line) and nothing else, so it doesn't misfire on a
# single heading that already contains real content after the masthead.
_MASTHEAD_TITLE_RE = re.compile(
    r'^\s*THE\s+WHITE\s+HOUSE\b(?:\s+Office\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z \'-]*)?\s*$',
    re.IGNORECASE,
)

# Matches when extracted text is nothing but a dateline (e.g. "June 27,
# 1996" or "December 8-9, 1998") - the signature of a <blockquote> that was
# auto-closed by the parser right after the dateline rather than where the
# archived HTML's author intended (see _extract_press_release_body).
_DATELINE_ONLY_RE = re.compile(
    r'^\s*(?:' + _WEEKDAYS + r',?\s+)?' + _MONTHS + r'\s+\d{1,2}(?:-\d{1,2})?,?\s*\d{4}\.?\s*$',
    re.IGNORECASE,
)


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

    # Compiled regexes matched against the START of the fully-extracted text
    # (after all DOM-level stripping above) and removed if found. For
    # boilerplate that isn't a removable DOM node but a fixed run of text at
    # the front of the page (nav banners, letterhead, repeated widget
    # content) that DOM-selector stripping can't target cleanly.
    # Override in subclasses, e.g.:
    #   LEADING_TEXT_STRIP_PATTERNS = (re.compile(r'^\s*Foo\b.*?\bBar\b\s*', re.IGNORECASE),)
    LEADING_TEXT_STRIP_PATTERNS = ()

    # Compiled regexes removed wherever they occur in the fully-extracted
    # text, not just at the start. For boilerplate inserted mid-page (e.g. a
    # breadcrumb/section label between the headline and body) that isn't
    # confined to a leading position. Verify the pattern never matches
    # legitimate content before adding one - unlike the leading patterns,
    # there's no position-based safety net here.
    # Override in subclasses, e.g.:
    #   MIDTEXT_STRIP_PATTERNS = (re.compile(r'\s*Foo Bar\b\s*'),)
    MIDTEXT_STRIP_PATTERNS = ()

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
    def _combine_headings(texts):
        """Join sibling heading elements into one title when there are
        exactly two (e.g. "III. New Community -" + "Fighting Crime"), since
        _extract_title otherwise only ever reads the first one. Three or
        more is ambiguous about what belongs together, so only the first is
        used in that case, same as before this existed.

        Skips the join when the first heading is masthead-only text (see
        _MASTHEAD_TITLE_RE) - joining would just prepend that boilerplate to
        the real title instead of letting _extract_title's masthead handling
        fall back to <title>, which gives a cleaner result on that template.

        Also skips the join when the two headings are the same text (some
        pages render an identical heading twice, just re-wrapped with a
        <br> in a different spot) - joining would just repeat the title.
        """
        texts = [t.strip() for t in texts if t.strip()]
        if not texts:
            return ''
        if _MASTHEAD_TITLE_RE.match(texts[0]):
            return texts[0]
        if len(texts) == 2:
            normalized = [re.sub(r'\s+', ' ', t).strip().lower() for t in texts]
            if normalized[0] != normalized[1]:
                return ' '.join(texts)
        return texts[0]

    @staticmethod
    def _extract_title(response):
        """Return the best available title for a page.

        Tries h1, h2, then <title> in order. The <title> fallback strips any
        embedded HTML tags — 1990s archived pages sometimes store markup like
        <font> or <b> as literal text inside <title> elements, which an HTML
        parser surfaces verbatim via ::text.
        """
        html_text = _HEADING_SPAN_RE.sub(
            lambda m: m.group(1) + _NESTED_BLOCK_TAG_RE.sub(' ', m.group(2)) + m.group(3),
            response.text,
        )
        sel = Selector(text=html_text)
        title = (
            ArchiveSpiderMixin._combine_headings(sel.css('h1').xpath('string(.)').getall())
            or ArchiveSpiderMixin._combine_headings(sel.css('h2').xpath('string(.)').getall())
        )
        if _MASTHEAD_TITLE_RE.match(title):
            # The heading is just the masthead - the real subject, if the
            # page has one at all, is in a second heading _extract_title
            # never reads. <title> reliably holds it on this template
            # (e.g. "Remarks - Alice Deal Jr. High School"), so prefer it
            # over the masthead when present.
            title_tag = remove_tags(sel.css('title::text').get(default='').strip())
            title = title_tag or title
        if not title:
            raw = sel.css('title::text').get(default='').strip()
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

    def _is_excluded_response(self, response):
        """Common parse_item entry check. A response can be non-text (e.g. a
        binary file served from an extension-less URL a link-following crawl
        swept up, indistinguishable from a real page by URL shape alone) or a
        frameset with no extractable content; css()/xpath() raise
        NotSupported on the former. Logs the appropriate exclusion and
        returns True if the response should be skipped."""
        if not isinstance(response, scrapy.http.TextResponse):
            self._log_exclusion(response.url, 'non_text_response')
            return True
        if response.css('frameset'):
            self._log_exclusion(response.url, 'frameset')
            return True
        return False

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

    def _extract_press_release_body(self, response):
        """Return the best available body text for Clinton-era pages.

        WH press releases wrap their entire body in <blockquote>, purely for
        its default indentation styling - a convenient way to skip the
        masthead/nav chrome that sits outside it, without needing the
        regex-based letterhead stripping used elsewhere. Non-press-release
        pages (OMB, CEQ, etc.) don't use blockquote at all, so this falls
        back to full body when there's no blockquote.

        Some archived pages never close that <blockquote> where the
        author's markup implies they meant to (the matching closing tag is
        often the very last one in the document, evidently meant to span
        the whole letter) - lxml's error correction then closes it early,
        right after a short leading fragment such as the dateline, leaving
        the real letter content stranded as body-level siblings the
        blockquote selector never sees. Falls through to body in that case
        rather than trusting a blockquote result that's just a dateline.
        """
        blockquote = self._extract_text(response, 'blockquote')
        if blockquote and not _DATELINE_ONLY_RE.match(blockquote):
            return blockquote
        return self._extract_text(response, 'body') or blockquote

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
        text = _INVISIBLE_RE.sub('', text)
        # Loop to a fixpoint rather than a single pass: letterhead components
        # (masthead, office, location, dateline) don't always appear in the
        # same order across pages (e.g. GWBush has "For Immediate Release"
        # before "Office of the Press Secretary"), so a later pattern in the
        # tuple may need to fire before an earlier one gets its turn.
        pre_strip_text = text
        for _ in range(8):
            new_text = text
            for pattern in self.LEADING_TEXT_STRIP_PATTERNS:
                new_text = pattern.sub('', new_text, count=1)
            if new_text == text:
                break
            text = new_text
        if not text.strip() and pre_strip_text.strip():
            # A page whose entire extracted text was just a dateline or
            # similar (e.g. a malformed <blockquote> that only captured
            # "November 22, 1996" from a formal letter's letterhead, a
            # pre-existing extraction gap unrelated to this stripping)
            # would otherwise end up completely empty. Keep the original
            # rather than trade a near-useless value for a useless one.
            text = pre_strip_text
        for pattern in self.MIDTEXT_STRIP_PATTERNS:
            text = pattern.sub(' ', text)
        if self.MIDTEXT_STRIP_PATTERNS:
            text = re.sub(r'\s+', ' ', text).strip()
        return text
