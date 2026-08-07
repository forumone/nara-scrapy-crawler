import html
import re
from urllib.parse import parse_qs, urlparse

import scrapy
from scrapy.selector import Selector
from scrapy.utils.gz import gunzip
from scrapy.utils.sitemap import Sitemap
from w3lib.html import remove_tags, remove_tags_with_content

from archive_crawler import exclusion_rules as _exclusion_rules_module
from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.exclusion_logging import ExclusionLoggingMixin

# Invisible Unicode format characters in archived HTML, plus the Unicode
# replacement character (U+FFFD, mojibake from a non-UTF8 source) - not
# invisible, but the same junk-artifact treatment applies.
_INVISIBLE_RE = re.compile('[\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\ufffd]')

# Matches a single h1/h2 span, non-greedy so it stops at the same closing
# tag lxml would.
_HEADING_SPAN_RE = re.compile(r'(<h[12]\b[^>]*>)(.*?)(</h[12]>)', re.IGNORECASE | re.DOTALL)
# An unclosed block tag inside a heading (e.g. "<h1>Foo<p>Bar</h1>") makes
# lxml auto-close the heading early, truncating it. Stripped from the
# heading span before parsing to keep the heading text intact.
_NESTED_BLOCK_TAG_RE = re.compile(
    r'</?(?:p|div|table|ul|ol|li|center|blockquote|tr|td|th)\b[^>]*>', re.IGNORECASE,
)

_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August'
    r'|September|October|November|December)'
)
_WEEKDAYS = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'

# Anchor text for a page's plain-text/no-graphics twin (e.g. "[Text
# version]") - a UI toggle link, not authored content, stripped regardless
# of the letterhead policy below.
TEXT_VERSION_TOGGLE_PATTERNS = (
    re.compile(r'^\s*\[\s*(?:Text|Graphics)\s+Version\s*\]\s*', re.IGNORECASE),
)

# Unused - not referenced by any spider's LEADING_TEXT_STRIP_PATTERNS. Kept
# rather than deleted: re-scraping to recover this text if it were needed
# again would cost far more than keeping tested regexes around unused.
#
# Only strips the masthead when immediately followed by a recognized
# continuation, never unconditionally, so it doesn't eat legitimate titles
# that happen to start with "The White House" (e.g. "The White House
# Visitors Office").
_RETIRED_PRESS_RELEASE_LETTERHEAD_PATTERNS = (
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
    re.compile(r'^\s*For\s+Immediate\s+Release\b\s*[:,]?\s*', re.IGNORECASE),
    re.compile(r'^\s*posted\s+by:?\s*The\s+White\s+House\b\s*', re.IGNORECASE),
    re.compile(r'^\s*Contact:?\s*[\d\-() ]{7,20}\s*', re.IGNORECASE),
    re.compile(r'^\s*' + _WEEKDAYS + r',?\s+' + _MONTHS + r'\s+\d{1,2},?\s*\d{4}\s*', re.IGNORECASE),
    re.compile(r'^\s*' + _MONTHS + r'\s+\d{1,2},?\s*\d{4}\s*', re.IGNORECASE),
)

# Clinton-era press-release pages (CW1-5) often have the masthead as its own
# heading, followed by a second heading with the real subject; _extract_title
# only reads the first heading, so it'd pick up the masthead instead. Matches
# only when the entire heading is masthead text, so it doesn't misfire on a
# heading that already contains real content after the masthead.
_MASTHEAD_TITLE_RE = re.compile(
    r'^\s*THE\s+WHITE\s+HOUSE\b(?:\s+Office\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z \'-]*)?\s*$',
    re.IGNORECASE,
)

# Matches text that's nothing but a dateline (e.g. "June 27, 1996") - the
# signature of a <blockquote> auto-closed right after the dateline instead
# of where the author intended (see _extract_press_release_body).
_DATELINE_ONLY_RE = re.compile(
    r'^\s*(?:' + _WEEKDAYS + r',?\s+)?' + _MONTHS + r'\s+\d{1,2}(?:-\d{1,2})?,?\s*\d{4}\.?\s*$',
    re.IGNORECASE,
)

# CW4/CW5 OMB PAYGO cost-estimate pages have no h1/h2/<title> a generic
# selector can use, but carry a machine-extractable "BILL TITLE: ... BILL
# PURPOSE:" field in the body, optionally followed by "LAW NUMBER: P.L.
# ###-###". No URL-path gating needed - the paired markers are specific
# enough not to false-positive on unrelated content.
_OMB_PAYGO_BILL_TITLE_RE = re.compile(
    r'BILL TITLE:\s*(.*?)\s*BILL PURPOSE:', re.IGNORECASE | re.DOTALL,
)
_OMB_PAYGO_LAW_NUMBER_RE = re.compile(r'LAW NUMBER:\s*(P\.?L\.?\s*[\d\-]+)', re.IGNORECASE)


def omb_paygo_title(body):
    """Return a composed title from an OMB PAYGO page's BILL TITLE/LAW
    NUMBER fields, or None if the body doesn't contain that pattern. Meant
    as a fallback after _extract_title comes up empty, not a replacement
    for it - see CW4/CW5's parse_item."""
    bill_m = _OMB_PAYGO_BILL_TITLE_RE.search(body)
    if not bill_m:
        return None
    bill_title = re.sub(r'\s+', ' ', bill_m.group(1)).strip()
    law_m = _OMB_PAYGO_LAW_NUMBER_RE.search(body)
    if law_m:
        return f'OMB PAYGO Cost Estimate: {bill_title} ({law_m.group(1).strip()})'
    return f'OMB PAYGO Cost Estimate: {bill_title}'


class ArchiveSpiderMixin(ExclusionLoggingMixin):
    # Every subclass without its own custom_settings gets one FEEDS entry
    # derived from SOURCE_SITE: data/<SOURCE_SITE>/<SOURCE_SITE>.csv. A
    # subclass that defines custom_settings itself (e.g. NavHarvesterMixin's
    # two-entry FEEDS, or generic_crawl's -O/-o output) is left alone.
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if 'custom_settings' not in cls.__dict__ and getattr(cls, 'SOURCE_SITE', None):
            cls.custom_settings = {
                'FEEDS': {
                    f'data/{cls.SOURCE_SITE}/{cls.SOURCE_SITE}.csv': {
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

    # Below this length (measured on the final full_text, after all
    # stripping/normalization), a non-empty body gets a 'short_body' warning
    # rather than being treated as ordinary content. Override per-spider, or
    # per-run via -a short_body_threshold=<N>; see _get_short_body_threshold.
    SHORT_BODY_THRESHOLD = 30

    # CSS selectors for site-specific boilerplate to strip, in addition to
    # the shared selectors (#menufloat, .mobile-select, etc.). Override in
    # subclasses, e.g.: EXTRA_STRIP_SELECTORS = ('a[href$=".header.html"]',)
    EXTRA_STRIP_SELECTORS = ()

    # XPath expressions for boilerplate CSS can't express (e.g. parent-of
    # conditions), applied in the same pass as EXTRA_STRIP_SELECTORS.
    # Override in subclasses, e.g.:
    #   EXTRA_STRIP_XPATH = ('.//center[.//img[@src="/911/images/star.gif"]]',)
    EXTRA_STRIP_XPATH = ()

    # Compiled regexes matched against the start of the fully-extracted text
    # and removed if found - for boilerplate that's a fixed run of text
    # (nav banners, letterhead) rather than a removable DOM node. Override
    # in subclasses, e.g.:
    #   LEADING_TEXT_STRIP_PATTERNS = (re.compile(r'^\s*Foo\b.*?\bBar\b\s*', re.IGNORECASE),)
    LEADING_TEXT_STRIP_PATTERNS = ()

    # Compiled regexes removed wherever they occur, not just at the start -
    # for boilerplate inserted mid-page (e.g. a breadcrumb between headline
    # and body). Verify a pattern never matches legitimate content before
    # adding one - no position-based safety net here. Override in
    # subclasses, e.g.:
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
        text = re.sub(r'([\W_])\1{4,} ?', '', text)
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
        """Join two sibling headings into one title (e.g. "III. New
        Community -" + "Fighting Crime"), since _extract_title otherwise
        only reads the first. Three or more is ambiguous, so only the first
        is used in that case.

        Skips the join when the first heading is masthead-only text (see
        _MASTHEAD_TITLE_RE), or when both headings are identical text (some
        pages render the same heading twice, just re-wrapped with a <br>)."""
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
        # :not(.element-invisible) excludes Drupal's screen-reader-only
        # utility class (e.g. a "Search form" label rendered as an h2 ahead
        # of a real heading on some obamawhitehouse Panels pages) - never
        # real visible content on any site.
        title = (
            ArchiveSpiderMixin._combine_headings(sel.css('h1:not(.element-invisible)').xpath('string(.)').getall())
            or ArchiveSpiderMixin._combine_headings(sel.css('h2:not(.element-invisible)').xpath('string(.)').getall())
        )
        if _MASTHEAD_TITLE_RE.match(title):
            # The heading is just the masthead - the real subject, if any,
            # is in a second heading _extract_title never reads. <title>
            # reliably holds it on this template, so prefer it when present.
            title_tag = remove_tags(sel.css('title::text').get(default='').strip())
            title = title_tag or title
        if not title:
            raw = sel.css('title::text').get(default='').strip()
            title = remove_tags(raw)
        title = re.sub(r'([\W_])\1{4,}', '', title)
        title = html.unescape(title)
        title = _INVISIBLE_RE.sub('', title)
        return re.sub(r'\s+', ' ', title).strip()

    def _get_short_body_threshold(self):
        # -a short_body_threshold=<N> arrives as a plain string instance
        # attribute via Scrapy's standard -a handling, hence the int() cast.
        return int(getattr(self, 'short_body_threshold', self.SHORT_BODY_THRESHOLD))

    def _slug_title(self, url):
        """Fallback title for a no_title row: last URL path segment, known
        extension stripped, '-'/'_' replaced with spaces, no title-casing
        (preserves acronyms like EO12902/AFVTBXL5 as-is). E.g.
        /omb/fedreg/pp99-1.html -> 'pp99 1'."""
        segment = urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]
        for ext in self._get_exclusion_rules().extensions.get('values', []):
            suffix = '.' + ext.lower()
            if segment.lower().endswith(suffix):
                segment = segment[:-len(suffix)]
                break
        return re.sub(r'[-_]+', ' ', segment).strip()

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
            self._log_dropped(failure.value.response.url, reason)
        else:
            self._log_dropped(failure.request.url, f'network_error:{failure.type.__name__}')

    @staticmethod
    def _is_redirect_wrapper(response):
        """A page whose entire content is a client-side meta-refresh to
        another URL (e.g. leftover "Redirecting..." pages from a
        URL-normalization pass) - not a real HTTP redirect, so Scrapy's
        redirect middleware never sees it and parse_item would otherwise
        extract the wrapper's own near-empty content. Detected by content
        rather than a maintained URL list - occurs site-wide on
        obamawhitehouse, not confined to one section."""
        for val in response.css('meta::attr(http-equiv)').getall():
            if val.strip().lower() == 'refresh':
                return True
        return False

    def _is_excluded_response(self, response):
        """Common parse_item entry check: a non-text response (e.g. a
        binary file at an extension-less URL), a frameset with no
        extractable content, or a client-side redirect wrapper page. Every
        caller reaches this only after a harvest row already exists for
        response.url, so this logs to _log_dropped, not _log_exclusion -
        scrape + drop = harvest holds against every reason logged here.
        Returns True if the response should be skipped."""
        if not isinstance(response, scrapy.http.TextResponse):
            self._log_dropped(response.url, 'non_text_response')
            return True
        if response.css('frameset'):
            self._log_dropped(response.url, 'frameset')
            return True
        if self._is_redirect_wrapper(response):
            self._log_dropped(response.url, 'redirect_wrapper')
            return True
        return False

    def _extract_press_release_body(self, response):
        """Best-available body text for Clinton-era pages. WH press
        releases wrap their body in <blockquote>, which conveniently skips
        the masthead/nav chrome outside it; non-press-release pages (OMB,
        CEQ, etc.) don't use blockquote, so this falls back to full body
        when there's none.

        Some archived pages never close that <blockquote> where the
        author's markup implies they meant to - lxml closes it early,
        right after a short leading fragment like the dateline, stranding
        the real content as body-level siblings the selector never sees.
        Falls through to body rather than trust a blockquote result that's
        just a dateline."""
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
        return self._clean_matched_html(match)

    def _extract_first_substantial(self, response, selector):
        """Like _extract_text, but for a CSS selector with multiple
        same-shape matches (e.g. a Drupal Panels page rendering 100+
        unrelated .field-item panes, where the first isn't the real
        content). Returns the first match whose cleaned text meets the
        short_body threshold, falling back to the first match if none
        clear it. CSS only."""
        if response.css('frameset'):
            return ''
        threshold = self._get_short_body_threshold()
        first_cleaned = None
        for match in response.css(selector).getall():
            cleaned = self._clean_matched_html(match)
            if first_cleaned is None:
                first_cleaned = cleaned
            if len(cleaned) >= threshold:
                return cleaned
        return first_cleaned or ''

    def _clean_matched_html(self, match):
        try:
            # iframe fallback content (e.g. an HTML-escaped YouTube-embed
            # fallback link) is never real page text - same treatment as
            # script/style.
            cleaned = remove_tags_with_content(match, which_ones=('script', 'style', 'iframe'))
        except TypeError:
            cleaned = ''
        # Boilerplate removed BEFORE the </div>->space substitution below -
        # doing it after leaves #menufloat unclosed, so lxml re-nests every
        # following sibling inside it, and removing it would delete all
        # body content.
        # #menufloat: NARA's Clinton-era banner. .mobile-select: Biden WH
        # mobile nav widget. table[summary*="Breadcrumbs"/"Print"]:
        # GWBush-era nav tables.
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
        # Strip repeated-punctuation runs (separators like "________" or
        # "********"), same as _teaser() already does for the teaser text.
        text = re.sub(r'([\W_])\1{4,} ?', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = _INVISIBLE_RE.sub('', text)
        # Loop to a fixpoint, not a single pass: letterhead components don't
        # always appear in the same order across pages, so a later pattern
        # may need to fire before an earlier one gets its turn.
        pre_strip_text = text
        for _ in range(8):
            new_text = text
            for pattern in self.LEADING_TEXT_STRIP_PATTERNS:
                new_text = pattern.sub('', new_text, count=1)
            if new_text == text:
                break
            text = new_text
        if not text.strip() and pre_strip_text.strip():
            # Keep the pre-strip text if stripping emptied it entirely
            # (e.g. a page whose only extracted text was a dateline) -
            # a near-useless value beats a useless one.
            text = pre_strip_text
        for pattern in self.MIDTEXT_STRIP_PATTERNS:
            text = pattern.sub(' ', text)
        if self.MIDTEXT_STRIP_PATTERNS:
            text = re.sub(r'\s+', ' ', text).strip()
        return text


class SitemapUrlSpiderMixin(ArchiveSpiderMixin):
    """Content spider that discovers its own URLs from a sitemap
    (SITEMAP_URL), folding sitemap/sitemapindex recursion into one
    start_requests that yields a parse_item request for every surviving
    leaf URL directly, rather than writing a harvest CSV for a separate run
    to read back.

    Kept off plain ArchiveSpiderMixin: a NavHarvesterMixin-composed spider
    also extends ArchiveSpiderMixin but crawls from start_urls, and needs
    to fall through to CrawlSpider/Spider's own start_requests untouched.

    REDIRECT_ENABLED stays False for both requests this mixin issues -
    none of the committed SITEMAP_URLs redirect, and a sub-sitemap that
    did would just log a warning (_log_sitemap_fetch_error), not need
    redirect-following logic."""

    def start_requests(self):
        sitemap_url = getattr(self, 'SITEMAP_URL', None)
        if not sitemap_url:
            raise ValueError(f"{type(self).__name__} must set SITEMAP_URL")
        self._seen_sitemap_urls = set()
        yield scrapy.Request(
            sitemap_url, callback=self._parse_sitemap, errback=self._log_sitemap_fetch_error,
        )

    def _parse_sitemap(self, response):
        body = response.body
        if body[:3] == b'\x1f\x8b\x08' or response.url.endswith('.gz'):
            body = gunzip(body)
        sitemap = Sitemap(body)

        if sitemap.type == 'sitemapindex':
            for entry in sitemap:
                loc = entry.get('loc', '')
                if loc:
                    yield scrapy.Request(
                        loc, callback=self._parse_sitemap, errback=self._log_sitemap_fetch_error,
                    )
            return

        rules = self._get_exclusion_rules()
        for entry in sitemap:
            url = entry.get('loc', '')
            if not url:
                continue
            key = url.lower()
            if key in self._seen_sitemap_urls:
                continue
            self._seen_sitemap_urls.add(key)
            if not _exclusion_rules_module.is_web_url(url, rules):
                ext = _exclusion_rules_module.url_extension(url)
                self._log_exclusion(url, f'extension:{ext}')
                continue
            reason = _exclusion_rules_module.match_exclude(url, rules)
            if reason:
                self._log_exclusion(url, reason)
                continue
            yield HarvestItem(url=url)
            yield self._make_request(url)

    def _log_sitemap_fetch_error(self, failure):
        from scrapy.spidermiddlewares.httperror import HttpError
        if failure.check(HttpError):
            status = failure.value.response.status
            if status < 400:
                self.logger.warning(
                    "Sub-sitemap request redirected (status %d), not followed: %s",
                    status, failure.value.response.url,
                )
                return
        self.logger.warning("Sitemap fetch failed: %s", failure.getErrorMessage())


class PetitionsSpiderMixin(ArchiveSpiderMixin):
    """Shared by obama_petitions.py and trump_petitions.py - the same
    Drupal petitions template, differing only in SOURCE_SITE/domain.
    _scrape_item dispatches on URL shape: a petition detail page
    (_parse_petition) gets its response-date appended to full_text; every
    other page uses the plainer _parse_generic (falls back to
    #content-main when there's no field-item body wrapper).

    Listed first in the MRO ahead of NavHarvesterMixin so this
    _scrape_item is found before NavHarvesterMixin's own
    _scrape_item = None default."""

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        # Pagination pages (`?page=N`) are followed for petition-link
        # discovery but carry no unique content - logged as dropped, not
        # just skipped, so scrape + drop = harvest still holds.
        parsed_url = urlparse(response.url)
        if 'page' in parse_qs(parsed_url.query) or parsed_url.path.rstrip('/') == '/responses':
            self._log_dropped(response.url, 'pagination_listing_page')
            return None
        if '/petition/' in response.url:
            return self._parse_petition(response)
        return self._parse_generic(response)

    def _parse_petition(self, response):
        warnings = []
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)

        date = re.sub(r'\s+', ' ', response.css('h4.petition-attribution::text').get(default='')).strip()
        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        full_text = f"{body} {date}".strip() if (date and any(c.isdigit() for c in date)) else body

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = full_text
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        return item

    def _parse_generic(self, response):
        warnings = []
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)

        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            body = self._extract_text(response, '#content-main')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        return item
