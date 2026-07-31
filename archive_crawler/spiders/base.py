import csv
import hashlib
import html
import os
import re
from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.selector import Selector
from w3lib.html import remove_tags, remove_tags_with_content

from archive_crawler import exclusion_rules as _exclusion_rules_module
from archive_crawler.items import HarvestItem

# Shared by _census_links across every spider that mixes in
# ExclusionLoggingMixin - stateless/config-only, safe to reuse. No
# allow_domains (we want external domains surfaced, not dropped) and
# deny_extensions=() (no IGNORED_EXTENSIONS - our own is_web_url is the sole
# authority on what's web-shaped). Scrapy's own _is_valid_url still silently
# drops non-http(s)/file/ftp schemes (mailto:/tel:/javascript:) with no way
# to override that - accepted as out of scope for the census, since these
# are a small enough share of overall link volume not to matter for
# explaining a page-count gap at the client's claimed scale.
_CENSUS_LINK_EXTRACTOR = LinkExtractor(deny_extensions=())

# Drupal Views always emits these two classes on a view's own wrapper
# element, in this fixed order, before any theme-added extra class that
# happens to share the same prefix (e.g. a suffixed view-display-id-page_1
# -most-recent following the canonical view-display-id-page_1) - see
# NavHarvesterMixin._view_identity.
_VIEW_ID_RE = re.compile(r'^view-id-(.+)$')
_VIEW_DISPLAY_ID_RE = re.compile(r'^view-display-id-(.+)$')

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

# Retired from active stripping 2026-07-31 (client-facing policy: scrape
# letterhead/dateline/contact text as-is, no warning column - see
# ~/.claude/projects/-home-caesius-git-scrapy/plans/
# content-remediation-policy-review-plan.md). No longer referenced by any
# spider's LEADING_TEXT_STRIP_PATTERNS. Kept, not deleted, in case a future
# post-hoc boilerplate-removal script is ever wanted - re-scraping to
# recover this text if it were deleted and needed again would cost far more
# than keeping already-tested regexes around unused.
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


def _spider_exclusion_rules(spider):
    """Load (and cache) a spider's exclusion_rules.ExclusionRules.

    Shared by ArchiveSpiderMixin and NavHarvesterMixin - both require a
    SOURCE_SITE class attribute naming the archive_crawler/exclusion_rules/
    <SOURCE_SITE>.yml file to load. Reads -a rules_file=<path> and
    -a rules_mode=append|replace for a per-run override; neither the
    committed file nor rules_file is ever written to.
    """
    if not hasattr(spider, '_exclusion_rules_cache'):
        spider._exclusion_rules_cache = _exclusion_rules_module.load_rules(
            spider.SOURCE_SITE,
            getattr(spider, 'rules_file', None),
            getattr(spider, 'rules_mode', 'append'),
        )
    return spider._exclusion_rules_cache


class ExclusionLoggingMixin:
    """Shared exclusion-rule access + logging for any spider with a
    SOURCE_SITE, regardless of whether it's a content spider, a nav
    harvester, or a listing harvester.

    Previously duplicated: ArchiveSpiderMixin and NavHarvesterMixin each
    defined their own identical _get_exclusion_rules, and only
    ArchiveSpiderMixin had _log_exclusion/closed() at all - meaning nav and
    listing harvesters had no way to log what they chose not to
    follow/yield. Factored out here so all three compose it instead of
    tripling that duplication.

    EXCLUSIONS_FILE_SUFFIX defaults to 'exclusions' (ArchiveSpiderMixin's
    existing filename, unchanged) - override per mixin/spider so a nav
    harvester, a listing harvester, and a content spider sharing the same
    SOURCE_SITE don't overwrite each other's exclusion log when run back to
    back (e.g. NavHarvesterMixin sets 'nav-exclusions').
    """

    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    def _get_exclusion_rules(self):
        return _spider_exclusion_rules(self)

    def _log_exclusion(self, url, reason):
        if not hasattr(self, '_exclusions'):
            self._exclusions = []
            self._logged_exclusion_urls = set()
        # Dedup by URL: a nav crawl can encounter the same excluded target
        # from many different referring pages (a sitewide-linked pattern, or
        # a url_list entry with many independent incoming links) - logging
        # every occurrence would bury the genuinely useful signal in
        # near-duplicate rows. Harmless for spiders that only ever consider
        # each URL once (e.g. the content spider reading a url_file), since
        # dedup never triggers there.
        if url in self._logged_exclusion_urls:
            return
        self._logged_exclusion_urls.add(url)
        self._exclusions.append({'url': url, 'reason': reason})

    def closed(self, reason):
        exclusions = getattr(self, '_exclusions', [])
        if not exclusions:
            return
        out_dir = os.path.join('data', self.SOURCE_SITE)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'{self.SOURCE_SITE}_{self.EXCLUSIONS_FILE_SUFFIX}.csv')
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'reason'])
            writer.writeheader()
            writer.writerows(exclusions)

    def _census_links(self, response):
        """Extract every <a>/<area> href on the page via a wide-open
        LinkExtractor (deny_extensions=() - see _CENSUS_LINK_EXTRACTOR) and
        log one of each URL's first occurrence under a widened reason set:
        this domain's rules:/nav_deny matches (the existing mechanism, now
        applied to every link on the page rather than just the ones a Rule's
        own LinkExtractor happened to extract) and non-web extensions.
        External-domain links are silently dropped, not logged - a naive
        mirror tool wouldn't plausibly "forget" to exclude other domains
        either, so this bucket isn't useful signal for explaining a
        same-domain page-count gap and would only inflate the log. Also does
        NOT see mailto:/tel:/javascript: links - Scrapy's own _is_valid_url
        drops any non-http(s)/file/ftp scheme unconditionally, with no way
        to override that short of bypassing LinkExtractor entirely, which
        isn't worth it for a share of link volume this small either.

        Built to make total site-wide hyperlink volume auditable against a
        client's page-count claim by reason - not to expand what gets
        crawled. Never schedules a Request for anything found here; this is
        extraction + classification only.

        Returns the URLs that don't fall into any of those buckets (real,
        same-domain, non-rule-excluded, HTML-shaped links) for callers that
        need a further check of their own - e.g. ArchiveSpiderMixin comparing
        against its own seed list to find content-page links never reached
        by nav/listing harvesting at all.
        """
        rules = self._get_exclusion_rules()
        allowed = set(d.lower() for d in (getattr(self, 'allowed_domains', None) or []))
        response_base = response.url.split('#', 1)[0]
        kept = []
        for link in _CENSUS_LINK_EXTRACTOR.extract_links(response):
            url = link.url
            if url.split('#', 1)[0] == response_base:
                continue
            host = urlparse(url).netloc.split(':')[0].lower()
            if allowed and host not in allowed:
                continue
            reason = _exclusion_rules_module.match_exclude(url, rules)
            if reason is not None:
                self._log_exclusion(url, reason)
                continue
            if not _exclusion_rules_module.is_web_url(url, rules):
                ext = _exclusion_rules_module.url_extension(url)
                self._log_exclusion(url, f'extension:{ext}')
                continue
            kept.append(url)
        return kept


class NavHarvesterMixin(ExclusionLoggingMixin):
    r"""Mixin for CrawlSpider-based nav harvesters.

    Provides listing-file exclusion, web-page URL filtering, and a parse_nav
    callback. Subclasses supply name, allowed_domains, start_urls, and rules.

    See HARVESTING.md for the full end-to-end process this mixin fits into,
    and ARCHITECTURE.md for the full listing-fingerprint mechanism design,
    its known limitations, and the decision rule for whether to enable it on
    a given site.

    listing_file is required
    ------------------------
    Every nav harvester must be given a dedup set of already-known content
    URLs via -a listing_file=<path> (a CSV with a url column; an empty file -
    header row only - is fine on a first run). This is not optional. A URL
    in that file is treated as already-known good content, so the nav
    crawler must not re-fetch, re-emit, or re-follow it.

    CSS-based listing detection (overriding _is_listing_page to inspect the
    response body) is intentionally not used to *exclude* pages here. In-page
    signals such as .views-row are unreliable: content pages that embed a
    "More Like This" block carry the same markup as listing pages and would
    be incorrectly excluded. URL-based pre-filtering via listing_file avoids
    this by relying on what a prior run actually found rather than
    assumptions about page structure.

    If a site is simple enough that a listing_file is unnecessary, it does not
    need this mixin at all — use generic_crawl_harvest instead.

    Automatic listing discovery, walk, and dedup
    ---------------------------------------------
    Listing discovery and pagination-walking are fully automatic, driven by a
    runtime fingerprint of each listing's item set - no curated seed list, no
    human review step between discovery and walking. Subclasses opt in by
    setting three attributes together: LISTING_VIEW_LINK_EXTRACTOR (a
    LinkExtractor scoped to the container a listing's item rows and pager
    share, e.g. LinkExtractor(restrict_css='.view') for Drupal Views),
    LISTING_CONTAINER_SELECTOR (a plain CSS selector string for that same
    container, e.g. '.view' - kept separate from LISTING_VIEW_LINK_EXTRACTOR
    rather than read back from its internal restrict_css, which Scrapy
    translates to XPath and merges into restrict_xpaths at construction time,
    indistinguishable from a directly-supplied XPath), and
    LISTING_PAGER_SELECTOR (a CSS selector matching only when a real,
    populated pager is present, e.g. '.pager-current') - a "view" container
    alone is not sufficient, since an ordinary content page that merely
    embeds a single-item "related content" widget can render inside the same
    container with real links but no pager.

    parse_nav evaluates every LISTING_CONTAINER_SELECTOR match on the page
    independently, not the page as a whole - a page carrying more than one
    genuinely paginated listing (confirmed to occur, e.g.
    obamawhitehouse's /energy/news, which renders two independently-paginated
    Views blocks side by side) gets one fingerprint check and, potentially,
    one walk per container, rather than merging them into a single check
    that only ever follows the first container's pager. is_listing (in the
    yielded item) is True if any container on the page has a populated
    pager.

    For each container with a populated pager, parse_nav fingerprints its
    item set (sha1 of the sorted URLs from _listing_pagination_items - the
    clean, template-specific item set scoped to that one container, not the
    wider container scan LISTING_VIEW_LINK_EXTRACTOR itself returns, which
    also picks up the container's own numbered pager links and so differs
    per permalink even for a byte-identical catalog) and combines it with
    the container's own Drupal view-id/view-display-id (parsed from its
    class attribute by _view_identity, e.g. view-id-most_recent
    view-display-id-page_1 - (None, None) if absent, e.g. a non-Drupal
    site). The combined (view_id, display_id, item_hash) key, not the item
    hash alone, is what gets checked against self._seen_listing_fingerprints
    - two containers whose entry pages happen to render an identical item
    set (e.g. a "recent posts" view and a "browse all" view, both sorted the
    same way) but come from different Views configurations no longer
    collide just because their top-N items coincide; the view identity has
    to agree too.

    If the key is new this run, parse_nav walks that container's full
    pagination via _walk_listing_pagination - fetching each extracted item
    through this same parse_nav callback (so the item's own outbound links
    get explored too, and a listing-shaped item gets the same fingerprint
    treatment with no special-casing). If the key has already been seen,
    that container's items and pager are flagged-via-is_listing and nothing
    inside it is walked or followed - this is what stops a shared catalog
    embedded on thousands of permalinks from being re-walked once per
    permalink. self._seen_listing_fingerprints is in-memory only, scoped to
    one crawl run.

    No link inside a matched container - item links and pager/filter
    controls alike - is ever followed via parse_nav's ordinary
    link-following loop, only via the dedicated walk above (this pooling
    still runs page-wide via LISTING_VIEW_LINK_EXTRACTOR/view_urls, since
    pooling is harmless for "don't double-follow" purposes even though
    fingerprinting/walking themselves are per-container). Links elsewhere on
    the page are followed normally (as is a .view container's own links
    when no pager is present anywhere on the page - it's just an ordinary
    embedded widget). The default (None for LISTING_VIEW_LINK_EXTRACTOR/
    LISTING_CONTAINER_SELECTOR/LISTING_PAGER_SELECTOR) disables the feature
    entirely, leaving parse_nav's link-following unconditional for
    subclasses that don't set them.

    FORCE_SKIP_LISTING_URLS is an escape hatch (empty by default, not
    required for normal operation): a URL in this set is always flagged
    is_listing and never auto-walked, regardless of its fingerprint - for a
    case where fingerprinting is confirmed to miss a real duplicate.

    LISTING_MAX_PAGES bounds a single container's pagination walk (default
    2000) as a defense-in-depth cap against an unbounded shared catalog: if
    walking exceeds it, _walk_listing_pagination stops and logs a warning
    rather than continuing silently.

    This mechanism has a known limitation (URL aliasing - two URL paths
    that alias the identical view hash differently and so both get walked
    in full) that is deliberately not fixed: it's bounded (linear in the
    number of distinct aliases a site actually defines, not the exponential
    per-embedding-permalink blowup this mechanism exists to prevent), and
    the extra items it surfaces in a harvest are themselves the signal that
    exposes the alias for a targeted rules: exclusion (see
    ARCHITECTURE.md's "Listing fingerprint dedup" section and www.
    obamawhitehouse.yml's /realitycheck rule for a worked example). Should
    not be enabled or disabled for a new site without discovery first - see
    ARCHITECTURE.md for the full decision rule.

    Subclasses that set LISTING_VIEW_LINK_EXTRACTOR/LISTING_CONTAINER_SELECTOR/
    LISTING_PAGER_SELECTOR must also implement _listing_pagination_items
    (return this container's item hrefs, template-specific) and
    _listing_pagination_next_url (return this container's next pagination
    page's href, or None) - see _walk_listing_pagination. Both take a single
    Selector scoped to one container (not the full response) - use
    response.urljoin(...) where absolute resolution is needed, since a
    container Selector has no urljoin of its own.

    Usage:
        # listing_file is required even on a first run - point it at an
        # empty CSV (header row only) when there's no prior harvest to seed
        # it with:
        #   echo "url" > data/mysite/mysite_empty-listing.csv
        #
        #   scrapy crawl mysite_harvest \
        #       -a listing_file=data/mysite/mysite_empty-listing.csv \
        #       -o data/mysite/mysite_harvest-full.csv

        class MySiteHarvestSpider(NavHarvesterMixin, CrawlSpider):
            name = "mysite_harvest"
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

    # Subclasses that need a different depth can override custom_settings
    # entirely, but keep CRAWLSPIDER_FOLLOW_LINKS: False if they do.
    # CrawlSpider's own built-in link-following runs unconditionally for
    # every start_urls response regardless of parse_nav, bypassing
    # _filter_web_urls and LISTING_VIEW_LINK_EXTRACTOR entirely - a listing
    # page placed directly in start_urls would leak its pager and item links
    # into the crawl via this path even though parse_nav's own manual loop
    # correctly excludes both. Only start_urls entries are exposed to this
    # (every later hop goes through this mixin's own response.follow(...,
    # callback=self.parse_nav) calls, not CrawlSpider's follow-machinery),
    # but disabling it entirely costs nothing since parse_nav's manual loop
    # is a complete replacement.
    custom_settings = {
        'DEPTH_LIMIT': 2,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
    }

    # Optional per-subclass hooks, all three required together: a
    # LinkExtractor scoped to the container a listing's pagination/filter
    # controls live in, a plain CSS selector string for that same container,
    # and a CSS selector matching only when a real pager is present. See
    # "Automatic listing discovery, walk, and dedup" above. None (the
    # default) disables the feature.
    LISTING_VIEW_LINK_EXTRACTOR = None
    LISTING_CONTAINER_SELECTOR = None
    LISTING_PAGER_SELECTOR = None

    # Escape hatch: a URL in this set is always flagged is_listing and never
    # auto-walked, regardless of its fingerprint. Empty by default and not
    # required for normal operation - see "Automatic listing discovery,
    # walk, and dedup" above.
    FORCE_SKIP_LISTING_URLS = frozenset()

    # Defense-in-depth cap on a single listing's pagination walk. See
    # "Automatic listing discovery, walk, and dedup" above.
    LISTING_MAX_PAGES = 2000

    # Distinct from ArchiveSpiderMixin's default 'exclusions' - a nav
    # harvester and its companion content spider share the same SOURCE_SITE,
    # so writing to the same filename would have one overwrite the other's
    # log whenever both run against the same site.
    EXCLUSIONS_FILE_SUFFIX = 'nav-exclusions'

    def __init__(self, listing_file=None, *args, **kwargs):
        if not listing_file:
            raise ValueError(
                "listing_file is required. On a first run, point it at an empty "
                "CSV (header row only): -a listing_file=data/mysite_empty-listing.csv"
            )
        super().__init__(*args, **kwargs)
        self._listing_urls = set()
        with open(listing_file, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                self._listing_urls.add(row['url'])
        # In-memory only, built up over one crawl run - see "Automatic
        # listing discovery, walk, and dedup" above.
        self._seen_listing_fingerprints = set()

    def _filter_web_urls(self, links):
        rules = self._get_exclusion_rules()
        return [lnk for lnk in links if _exclusion_rules_module.is_web_url(lnk.url, rules)]

    def _apply_nav_deny(self, links):
        """Drop links matching this domain's nav_deny regex patterns OR its
        rules: entries (archive_crawler/exclusion_rules/<SOURCE_SITE>.yml).
        Checking rules: here too means an out-of-scope URL (e.g. a
        non-English mirror) only needs one entry to be excluded from both
        the nav crawl and the content spider, instead of a duplicate in each
        list. nav_deny stays available for exclusions that should hold the
        nav crawler back without also excluding the URL from a content
        scrape reached some other way (e.g. a known-duplicate URL shape not
        worth nav-following into, but fine to scrape if it ends up in a
        url_file regardless).

        Called directly from parse_nav's own manual link-following loop, not
        via a Rule's process_links= - CRAWLSPIDER_FOLLOW_LINKS is set False
        in custom_settings specifically so CrawlSpider's own built-in
        Rule-dispatch machinery (which would call rule.process_links, but
        skips _filter_web_urls and LISTING_VIEW_LINK_EXTRACTOR entirely)
        never runs at all. Do not wire this as a Rule's process_links= in a
        subclass - it would be dead configuration since that codepath never
        executes, and reads as if a second, redundant filtering mechanism is
        in play when there isn't one.

        Every dropped link is logged via _log_exclusion (deduped by URL, see
        ExclusionLoggingMixin) so a shortfall in final harvest counts can be
        checked against what was deliberately excluded here, rather than
        left indistinguishable from a link the crawl simply never found.
        Scoped to rules:/nav_deny matches only - not is_listing_page's
        listing_file skip (a different mechanism entirely, not an
        exclusion-rule match) and not _filter_web_urls' non-web-URL
        filtering (mailto:/external links etc. - high volume, not useful
        signal for this diagnostic).
        """
        rules = self._get_exclusion_rules()
        patterns = _exclusion_rules_module.nav_deny_patterns(rules)
        kept = []
        for lnk in links:
            reason = _exclusion_rules_module.match_exclude(lnk.url, rules)
            if reason is not None:
                self._log_exclusion(lnk.url, reason)
                continue
            nav_deny_match = next((p for p in patterns if re.search(p, lnk.url)), None)
            if nav_deny_match is not None:
                self._log_exclusion(lnk.url, f'nav_deny:{nav_deny_match}')
                continue
            kept.append(lnk)
        return kept

    def _is_listing_page(self, response):
        """Return True if this URL should be skipped entirely.

        Despite the name, this checks whether the URL is already-known
        content (from listing_file), not whether the page itself is a
        listing - see the "listing_file is required" section above. Kept as
        an overridable hook in case a subclass ever needs a genuinely
        different skip condition, but do not add CSS-based listing detection
        here - use LISTING_VIEW_LINK_EXTRACTOR (flag, don't exclude) instead.
        """
        return response.url in self._listing_urls

    @staticmethod
    def _listing_fingerprint(view_urls):
        """sha1 of the sorted item-URL set extracted from one listing
        container, as first encountered. Two listing pages that render the
        exact same item set (e.g. every video permalink's embedded "browse
        other videos" catalog) hash identically regardless of which
        textually-distinct URL each copy lives at - see "Automatic listing
        discovery, walk, and dedup" above. Combined with _view_identity into
        a composite key by parse_nav - this hash alone is not the dedup key."""
        digest = hashlib.sha1()
        for url in sorted(view_urls):
            digest.update(url.encode('utf-8'))
            digest.update(b'\n')
        return digest.hexdigest()

    @staticmethod
    def _view_identity(container):
        """Return (view_id, display_id) parsed from a Drupal Views
        container's own class attribute (view-id-<machine name>,
        view-display-id-<display id>), or (None, None) if the container
        carries no such classes (e.g. a non-Drupal site). Takes the first
        matching class token in DOM order - Drupal always emits the
        canonical view-id-*/view-display-id-* classes before any
        theme-added extra class sharing the same prefix (confirmed live:
        view-display-id-page_1 followed by a theme-added
        view-display-id-page_1-most-recent). Used by parse_nav to
        distinguish two different Views configurations whose item sets
        happen to coincide, and by _select_container to re-locate the same
        container across a listing's own pagination pages."""
        classes = (container.attrib.get('class') or '').split()
        view_id = next(
            (m.group(1) for c in classes if (m := _VIEW_ID_RE.match(c))), None,
        )
        display_id = next(
            (m.group(1) for c in classes if (m := _VIEW_DISPLAY_ID_RE.match(c))), None,
        )
        return view_id, display_id

    def parse_nav(self, response):
        """Yield the URL and follow links if this is a nav content page.

        Pages in listing_file (already known listing URLs) are dropped
        entirely — no item yielded and no links followed. This prevents the
        spider from fanning out into known listing sections and their
        thousands of content URLs.

        Every LISTING_CONTAINER_SELECTOR match on the page is evaluated
        independently - see "Automatic listing discovery, walk, and dedup"
        above for the full walk/dedup mechanism, including the composite
        (view_id, display_id, item_hash) fingerprint key. is_listing/depth
        are yielded once per page (True if any container has a populated
        pager). No link inside a matched container is followed via the
        ordinary loop below — items and pager/filter controls alike; other
        links on the page are followed normally.

        Links are followed manually (rather than via follow=True in the Rule)
        so that we can gate following on these per-page checks. Subclass
        rules must set follow=False and omit process_links - the latter
        would be dead configuration, since CRAWLSPIDER_FOLLOW_LINKS: False in
        custom_settings means CrawlSpider's own Rule-dispatch machinery
        (which calls rule.process_links) never runs.

        The web-URL guard is applied to response.url as well as to extracted
        links because start_urls entries reach this callback (via
        parse_start_url) without ever passing through _filter_web_urls -
        that only runs on links extracted from an already-fetched response,
        not on the seed URLs themselves.
        """
        if not _exclusion_rules_module.is_web_url(response.url, self._get_exclusion_rules()):
            return
        if self._is_listing_page(response):
            return
        view_urls = set()
        listing_containers = []
        if (self.LISTING_VIEW_LINK_EXTRACTOR is not None
                and self.LISTING_CONTAINER_SELECTOR is not None
                and self.LISTING_PAGER_SELECTOR is not None):
            containers = response.css(self.LISTING_CONTAINER_SELECTOR)
            listing_containers = [
                (index, container) for index, container in enumerate(containers)
                if container.css(self.LISTING_PAGER_SELECTOR)
            ]
            if listing_containers:
                view_urls = {lnk.url for lnk in self.LISTING_VIEW_LINK_EXTRACTOR.extract_links(response)}
        yield HarvestItem(
            url=response.url,
            is_listing=bool(listing_containers),
            depth=response.request.meta.get('depth', 0) if response.request else 0,
        )
        self._census_links(response)
        if response.url not in self.FORCE_SKIP_LISTING_URLS:
            for index, container in listing_containers:
                # Fingerprint _listing_pagination_items, NOT view_urls - the
                # latter also includes the container's own numbered pager
                # links, which point back to THIS permalink's own URL and so
                # differ per permalink even for a byte-identical catalog
                # (see the mixin's own docstring).
                item_urls = {response.urljoin(href) for href in self._listing_pagination_items(container)}
                view_id, display_id = self._view_identity(container)
                # Register before walking, not after - avoids a race where
                # two near-simultaneous discoveries of the same shared
                # catalog both start walking before either finishes.
                key = (view_id, display_id, self._listing_fingerprint(item_urls))
                if key in self._seen_listing_fingerprints:
                    continue
                self._seen_listing_fingerprints.add(key)
                yield from self._walk_listing_pagination(
                    response, container_index=index, view_id=view_id,
                    display_id=display_id, _skip_census=True,
                )
        if not listing_containers:
            yield from self._maybe_scrape_item(response)
        for rule in self._rules:
            links = self._apply_nav_deny(self._filter_web_urls(rule.link_extractor.extract_links(response)))
            for link in links:
                if link.url in view_urls:
                    continue
                yield response.follow(link.url, callback=self.parse_nav)

    def _maybe_scrape_item(self, response):
        """No-op unless a subclass also composes ArchiveSpiderMixin and
        defines _scrape_item (site-specific content extraction, same role
        as a standalone spider's parse_item). A subclass composing only
        NavHarvesterMixin (e.g. open_obama_whitehouse_harvest.py, or a new
        site explored before its content-extraction selectors are written)
        shares this parse_nav unchanged and stays harvest-only. A subclass
        that also defines _scrape_item (e.g. letsmove.py,
        obama_whitehouse.py) extracts content inline on the same response
        already fetched for nav discovery - no second fetch."""
        scrape_item = getattr(self, '_scrape_item', None)
        if scrape_item is None:
            return
        item = scrape_item(response)
        if item is not None:
            yield item

    # CrawlSpider routes each start_urls response through parse_start_url
    # instead of the Rule's callback, so without this override a listing
    # page placed directly in start_urls would bypass _is_listing_page and
    # LISTING_VIEW_LINK_EXTRACTOR entirely on its first fetch - fanning out
    # into its full item/pager range unfiltered. Delegating unifies the two
    # entry points onto identical logic.
    parse_start_url = parse_nav

    def _listing_pagination_items(self, container):
        """Return this listing container's item hrefs (template-specific
        CSS/xpath, e.g. '.views-row h2 a::attr(href)'), scoped to the single
        container Selector parse_nav passes in - not the whole response.
        Required override for any subclass that sets
        LISTING_VIEW_LINK_EXTRACTOR/LISTING_CONTAINER_SELECTOR/
        LISTING_PAGER_SELECTOR - see _walk_listing_pagination."""
        raise NotImplementedError(
            f'{type(self).__name__} sets LISTING_VIEW_LINK_EXTRACTOR/'
            'LISTING_CONTAINER_SELECTOR/LISTING_PAGER_SELECTOR but does not '
            'implement _listing_pagination_items'
        )

    def _listing_pagination_next_url(self, container):
        """Return this listing container's next-page href, or None if this
        is the last page. Scoped to the single container Selector parse_nav
        passes in, same as _listing_pagination_items. Required override
        alongside _listing_pagination_items - see _walk_listing_pagination."""
        raise NotImplementedError(
            f'{type(self).__name__} sets LISTING_VIEW_LINK_EXTRACTOR/'
            'LISTING_CONTAINER_SELECTOR/LISTING_PAGER_SELECTOR but does not '
            'implement _listing_pagination_next_url'
        )

    def _select_container(self, response, container_index, view_id, display_id):
        """Re-locate 'the same' listing container on a later page of this
        container's own pagination walk. Prefers matching by the
        container's own persistent Drupal view-id/view-display-id (stable
        across a listing's own pagination pages - only view-dom-id is
        randomized per-request, and this isn't it), falling back to
        positional index only if no container's identity matches (e.g.
        view_id/display_id are (None, None) because the site isn't Drupal,
        or the site's own markup changed shape between pages). Positional
        fallback assumes container order is stable across a listing's own
        paginated pages - a reasonable assumption for how Views-rendered
        pages work in practice (the same template renders its blocks in the
        same order on every page), but not logically guaranteed - hence
        preferring the identity match first."""
        containers = response.css(self.LISTING_CONTAINER_SELECTOR)
        if view_id is not None or display_id is not None:
            for container in containers:
                if self._view_identity(container) == (view_id, display_id):
                    return container
            self.logger.warning(
                'Listing pagination at %s: no container matched view '
                'identity (%r, %r) seen on the entry page - falling back '
                'to positional index %d, which may pick the wrong '
                'container if page layout shifted.',
                response.url, view_id, display_id, container_index,
            )
        return containers[container_index]

    def _walk_listing_pagination(
        self, response, container_index, view_id=None, display_id=None,
        _page_count=1, _skip_census=False,
    ):
        """Walk one listing container's full pagination automatically,
        fetching each extracted item through parse_nav (rather than merely
        recording its URL) so the item's own outbound links get explored too
        - see "Automatic listing discovery, walk, and dedup" above. Recurses
        through subsequent pages via this same callback; only the entry
        page's fingerprint gets checked (in parse_nav) - a fresh fingerprint
        check per pagination page isn't needed since the whole chain is only
        ever reached once, from that one fingerprint-gated call.

        container_index/view_id/display_id identify which of this page's
        LISTING_CONTAINER_SELECTOR matches to operate on - re-selected fresh
        via _select_container on every pagination page fetched through this
        method's own recursive response.follow(...,
        cb_kwargs={'container_index': ..., 'view_id': ..., 'display_id':
        ...}) call, not carried over as a Selector object across requests
        (a Selector is scoped to the response it came from, so a later
        page's container has to be re-selected from that page's own
        response regardless).

        _skip_census avoids double-logging the entry page's census (parse_nav
        already ran it on that same response before dispatching here) without
        skipping it for every later page in the chain, which never go through
        parse_nav at all.
        """
        container = self._select_container(response, container_index, view_id, display_id)
        rules = self._get_exclusion_rules()
        for href in self._listing_pagination_items(container):
            url = response.urljoin(href)
            reason = _exclusion_rules_module.match_exclude(url, rules)
            if reason is not None:
                self._log_exclusion(url, reason)
                continue
            yield response.follow(url, callback=self.parse_nav)

        if not _skip_census:
            self._census_links(response)

        if _page_count >= self.LISTING_MAX_PAGES:
            self.logger.warning(
                'Listing pagination at %s (container %d) hit '
                'LISTING_MAX_PAGES=%d without reaching its last page - '
                'aborting walk. Possible fingerprinting failure to collapse '
                'a shared/duplicate catalog; investigate before trusting '
                'this listing\'s harvested items.',
                response.url, container_index, self.LISTING_MAX_PAGES,
            )
            return

        next_href = self._listing_pagination_next_url(container)
        if next_href:
            yield response.follow(
                next_href, callback=self._walk_listing_pagination,
                cb_kwargs={
                    'container_index': container_index,
                    'view_id': view_id,
                    'display_id': display_id,
                    '_page_count': _page_count + 1,
                },
            )


class ArchiveSpiderMixin(ExclusionLoggingMixin):
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
