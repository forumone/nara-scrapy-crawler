import csv
import html
import re
from urllib.parse import parse_qs, urlparse

import scrapy
from scrapy.selector import Selector
from w3lib.html import remove_tags, remove_tags_with_content

from archive_crawler import exclusion_rules as _exclusion_rules_module
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.exclusion_logging import ExclusionLoggingMixin

# Invisible Unicode format characters that appear in archived source HTML.
# Soft hyphen (U+00AD), zero-width space/non-joiner/joiner (U+200B-D),
# directional marks (U+200E-F), BOM/ZWNBSP (U+FEFF). Also strips the Unicode
# replacement character (U+FFFD) here too: genuine mojibake from a non-UTF8
# byte in the archived source, not invisible, but the same "junk artifact to
# remove" treatment applies.
_INVISIBLE_RE = re.compile('[\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\ufffd]')

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

# Anchor text for a page's plain-text/no-graphics twin, e.g. "[Text version]"
# linking wf-work.html to wf-work-plain.html - a UI toggle link, not authored
# content, so it stays stripped regardless of the letterhead policy below.
# Flattened into ordinary text by _extract_text's tag-stripping,
# indistinguishable from real content by the time this pattern runs.
TEXT_VERSION_TOGGLE_PATTERNS = (
    re.compile(r'^\s*\[\s*(?:Text|Graphics)\s+Version\s*\]\s*', re.IGNORECASE),
)

# Currently unused - not referenced by any spider's LEADING_TEXT_STRIP_PATTERNS.
# TODO: decide whether to keep or delete once client direction on letterhead
# removal is settled. Kept for now, not deleted, in case a future post-hoc
# boilerplate-removal script is ever wanted - re-scraping to recover this
# text if it were deleted and needed again would cost far more than keeping
# already-tested regexes around unused.
#
# Components appeared in varying combinations and order on CW1-6/GWBush
# (e.g. GWBush puts "For Immediate Release" before "Office of the Press
# Secretary"), which is why this was applied in a fixpoint loop rather than
# a single pass when it was active - see _extract_text's git history.
#
# The masthead only stripped when immediately followed by a recognized
# continuation, never unconditionally, so it didn't eat legitimate titles
# that happen to start with "The White House" (e.g. "The White House
# Visitors Office" or "The White House Conference on the New Economy").
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

# CW4/CW5 OMB PAYGO cost-estimate pages (same report series, different alias
# directory per site) have no h1/h2/<title> a generic selector can use, but
# carry a machine-extractable "BILL TITLE: ... BILL PURPOSE:" field in the
# body text itself, optionally followed by "LAW NUMBER: P.L. ###-###". No
# URL-path gating needed - the paired BILL TITLE/BILL PURPOSE markers are
# specific enough not to false-positive on unrelated content.
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
    # Every subclass that doesn't set its own custom_settings gets a single
    # FEEDS entry derived from SOURCE_SITE: data/<SOURCE_SITE>/<SOURCE_SITE>.csv,
    # matching every other spider's automatic-output convention (see
    # ExclusionLoggingMixin.closed for the same derivation applied to the
    # exclusions CSV). A subclass that defines its own custom_settings (e.g.
    # a NavHarvesterMixin site with two FEEDS entries, or generic_crawl's
    # -O/-o-driven output) is left alone.
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
        # :not(.element-invisible) excludes Drupal's screen-reader-only
        # utility class (e.g. a "Search form" accessibility label rendered
        # as an h2 ahead of any real heading on some obamawhitehouse Panels
        # pages) - never real visible content on any site, not a
        # site-specific judgment call.
        title = (
            ArchiveSpiderMixin._combine_headings(sel.css('h1:not(.element-invisible)').xpath('string(.)').getall())
            or ArchiveSpiderMixin._combine_headings(sel.css('h2:not(.element-invisible)').xpath('string(.)').getall())
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
        /omb/fedreg/pp99-1.html -> 'pp99 1'. Synthesized, not authored - the
        warnings column's own no_title marker is what signals that, so no
        extra bracket-wrapping is added here."""
        segment = urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]
        for ext in self._get_exclusion_rules().extensions.get('values', []):
            suffix = '.' + ext.lower()
            if segment.lower().endswith(suffix):
                segment = segment[:-len(suffix)]
                break
        return re.sub(r'[-_]+', ' ', segment).strip()

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

    @staticmethod
    def _is_redirect_wrapper(response):
        """A page whose entire content is a client-side meta-refresh to a
        canonical URL elsewhere (e.g. archived-site "Redirecting..." pages
        left behind by a URL-normalization pass) - not present as an actual
        HTTP redirect, so Scrapy's own redirect middleware never sees it and
        parse_item would otherwise extract this wrapper's own near-empty
        "Redirecting..." title/body as if it were real content. Confirmed to
        occur site-wide on obamawhitehouse, not confined to one URL shape or
        section - detected generically by content rather than by a maintained
        URL list."""
        for val in response.css('meta::attr(http-equiv)').getall():
            if val.strip().lower() == 'refresh':
                return True
        return False

    def _is_excluded_response(self, response):
        """Common parse_item entry check. A response can be non-text (e.g. a
        binary file served from an extension-less URL a link-following crawl
        swept up, indistinguishable from a real page by URL shape alone), a
        frameset with no extractable content, or a client-side redirect
        wrapper page; css()/xpath() raise NotSupported on the first. Logs the
        appropriate exclusion and returns True if the response should be
        skipped."""
        if not isinstance(response, scrapy.http.TextResponse):
            self._log_exclusion(response.url, 'non_text_response')
            return True
        if response.css('frameset'):
            self._log_exclusion(response.url, 'frameset')
            return True
        if self._is_redirect_wrapper(response):
            self._log_exclusion(response.url, 'redirect_wrapper')
            return True
        return False

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
        return self._clean_matched_html(match)

    def _extract_first_substantial(self, response, selector):
        """Like _extract_text, but for a CSS selector with multiple
        same-shape candidate matches in document order (e.g. a Drupal
        Panels landing page rendering 100+ unrelated .field-item panes,
        where the first in document order can be an unrelated
        video-embed-fallback link rather than the real content). Returns
        the first match whose cleaned text meets the short_body threshold,
        skipping earlier matches that clean down to nothing or near-nothing.
        Falls back to the first match's own cleaned text (same result
        _extract_text would give) if none clear the threshold - CSS only,
        not meant for XPath selectors."""
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
            # iframe: browser-fallback content inside the tag (e.g. a
            # YouTube embed's fallback <a> link, sometimes stored literally
            # HTML-escaped, e.g. "&lt;a href=...&gt;") is never real visible
            # page text - same non-content status as script/style, applied
            # uniformly rather than as a site-specific judgment call.
            cleaned = remove_tags_with_content(match, which_ones=('script', 'style', 'iframe'))
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
        # Strip repeated-punctuation runs (separators like "________" or
        # "********"), same as _teaser() already does for the teaser text.
        text = re.sub(r'([\W_])\1{4,} ?', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
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


class UrlFileSpiderMixin(ArchiveSpiderMixin):
    """For a content spider whose only input is a url_file CSV (one 'url'
    column) - the sitemap-based spiders (clintonwhitehouse1-6,
    bidenwhitehouse, georgewbush_whitehouse). Deliberately NOT part of
    plain ArchiveSpiderMixin: a NavHarvesterMixin-composed spider (which
    also extends ArchiveSpiderMixin, for its content-extraction helpers)
    crawls from start_urls instead and must fall through to CrawlSpider/
    Spider's own start_requests - putting url_file-reading here instead of
    on ArchiveSpiderMixin means that fallthrough needs no special-casing
    anywhere, in either direction."""

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError(
                "url_file argument is required: "
                f"-a url_file=data/{self.SOURCE_SITE}/{self.SOURCE_SITE}_harvest.csv"
            )
        rules = self._get_exclusion_rules()
        with open(url_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                url = row['url']
                reason = _exclusion_rules_module.match_exclude(url, rules)
                if reason:
                    self._log_exclusion(url, reason)
                else:
                    yield self._make_request(url)

    def _make_request(self, url, **kwargs):
        kwargs.setdefault('callback', self.parse_item)
        kwargs.setdefault('errback', self._log_http_error)
        return scrapy.Request(url, **kwargs)


class PetitionsSpiderMixin(ArchiveSpiderMixin):
    """Shared by obama_petitions.py and trump_petitions.py - the same
    Drupal petitions-site template, differing only in SOURCE_SITE/domain.
    _scrape_item dispatches on URL shape: a petition detail page
    (_parse_petition) gets its response-date appended to full_text when one
    is present; every other page (listing, about, etc.) uses the plainer
    _parse_generic, which also falls back to #content-main for pages
    without the standard field-item body wrapper.

    Composed alongside NavHarvesterMixin by both spiders, listed first in
    the MRO (`class ObamaPetitionsSpider(PetitionsSpiderMixin,
    NavHarvesterMixin, CrawlSpider)`) so this _scrape_item is found before
    NavHarvesterMixin's own _scrape_item = None default."""

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        # Root/`/responses` pagination pages (`?page=N`) are followed for
        # petition-link discovery (see NavHarvesterMixin's pagination walk)
        # but carry no unique content of their own - logged as an exclusion
        # (not just skipped) so harvest = scrape + exclude still holds.
        parsed_url = urlparse(response.url)
        if 'page' in parse_qs(parsed_url.query) or parsed_url.path.rstrip('/') == '/responses':
            self._log_exclusion(response.url, 'pagination_listing_page')
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
