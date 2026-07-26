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
    re.compile(r'^\s*For\s+Immediate\s+Release\b\s*[:,]?\s*', re.IGNORECASE),
    re.compile(r'^\s*posted\s+by:?\s*The\s+White\s+House\b\s*', re.IGNORECASE),
    re.compile(r'^\s*Contact:?\s*[\d\-() ]{7,20}\s*', re.IGNORECASE),
    re.compile(r'^\s*' + _WEEKDAYS + r',?\s+' + _MONTHS + r'\s+\d{1,2},?\s*\d{4}\s*', re.IGNORECASE),
    re.compile(r'^\s*' + _MONTHS + r'\s+\d{1,2},?\s*\d{4}\s*', re.IGNORECASE),
    # Anchor text for a page's plain-text/no-graphics twin, e.g.
    # "[Text version]" linking wf-work.html to wf-work-plain.html. Flattened
    # into ordinary text by _extract_text's tag-stripping, indistinguishable
    # from real content by the time this pattern runs.
    re.compile(r'^\s*\[\s*(?:Text|Graphics)\s+Version\s*\]\s*', re.IGNORECASE),
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

    See HARVESTING.md for the full end-to-end process this mixin fits into.

    listing_file is required
    ------------------------
    Every nav harvester must be given the output of its companion
    *_harvest_list spider via -a listing_file=<path>. This is not optional.

    The listing file is the *_harvest_list spider's own output: individual
    content-item URLs it extracted from known listing pages' .views-row
    entries while walking their pagination - NOT the listing pages'
    own URLs. It is loaded into _listing_urls at startup as a dedup set: a
    URL in that set is already known good content harvested the efficient
    way (direct pagination walk), so the nav crawler must not re-fetch,
    re-emit, or re-follow it - doing so would just waste budget rediscovering
    thousands of already-known content URLs by wandering the nav graph.

    CSS-based listing detection (overriding _is_listing_page to inspect the
    response body) is intentionally not used to *exclude* pages in split
    harvesters. In-page signals such as .views-row are unreliable: content
    pages that embed a "More Like This" block carry the same markup as
    listing pages and would be incorrectly excluded. URL-based pre-filtering
    avoids this class of error entirely by relying on what the list harvester
    actually found rather than on assumptions about page structure.

    If a site is simple enough that a listing_file is unnecessary, it does not
    need a split harvester — use generic_crawl_harvest instead.

    Automatic listing discovery, walk, and dedup
    ---------------------------------------------
    listing_file only pre-filters *known* content URLs from a prior run (see
    above). Listing discovery and pagination-walking themselves are fully
    automatic, driven by a runtime fingerprint - no curated seed list, no
    human review step between discovery and walking.

    Subclasses opt in by setting LISTING_VIEW_LINK_EXTRACTOR to a
    LinkExtractor scoped to the container a listing's pagination is attached
    to (e.g. Drupal Views' own wrapper, LinkExtractor(restrict_css='.view') —
    confirmed on obamawhitehouse to enclose both the item rows and the pager
    across multiple distinct view templates, teaser-card and table-gallery
    alike) AND LISTING_PAGER_SELECTOR to a CSS selector matching only when a
    real pager is present (e.g. '.pager-current', confirmed on both
    templates). Both must be set together and both must match for a page to
    be treated as a listing - a "view" container alone is NOT sufficient.
    Confirmed empirically this matters: ordinary content/topic pages that
    merely embed a "related videos"/"related blog posts" widget also render
    inside a .view-classed container with real links, but carry no pager at
    all (unlike the single-item-embed false positive this was originally
    built to avoid, which doesn't even have a .view wrapper) - restrict_css
    alone flags these as false-positive listings and, worse, excludes their
    related-content links from being followed, which can genuinely miss a
    page only ever linked from inside one of these widgets. Requiring a
    populated pager closes both problems at once.

    When both match, parse_nav flags the page in the output (url + is_listing
    + depth) AND fingerprints the page's clean, template-specific item set -
    _listing_pagination_items(response), sha1 of the sorted tuple, see
    _listing_fingerprint - NOT the wider view_urls set LISTING_VIEW_LINK_EXTRACTOR
    extracts from the whole .view container. That wider set also includes the
    container's own numbered pager links (a Drupal pager renders nearby page
    numbers, not just a single "next" arrow), which point back to THAT
    permalink's own URL and so differ per permalink even when the real catalog
    items are byte-identical - fingerprinting view_urls directly would silently
    defeat the whole dedup mechanism (confirmed during smoke-testing: two
    photogallery permalinks sharing an identical 8-item catalog hashed
    differently until the fingerprint was switched to the clean item set).
    If the fingerprint is new (this exact item set has never been walked this
    run), the listing's full
    pagination gets walked automatically via _walk_listing_pagination, and
    each extracted item is fetched through this same parse_nav callback
    (response.follow(item_url, callback=self.parse_nav)) rather than merely
    recorded - so an item's own outbound links get explored too, and if the
    item itself turns out to be another listing-shaped page (e.g. a video
    permalink embedding the sitewide "browse other videos" catalog), the same
    fingerprint check flags-and-skips it with no special-casing. If the
    fingerprint has already been seen, the page is flagged and nothing inside
    the container is walked or followed - this is what stops a byte-identical
    shared catalog embedded on thousands of distinct permalinks from being
    re-walked once per permalink (see obama_whitehouse_harvest.py's own
    module docstring for the concrete case this defends against).
    self._seen_listing_fingerprints is in-memory only, built up over one
    crawl run, matching how _logged_exclusion_urls already works.

    FORCE_SKIP_LISTING_URLS is an escape hatch (empty by default, not
    required for normal operation): a URL in this set is always flagged
    is_listing and never auto-walked, regardless of its fingerprint - a
    manual override in case fingerprinting is ever confirmed to miss a real
    duplicate on some future site, without reintroducing a curation
    dependency for the common case.

    LISTING_MAX_PAGES bounds a single listing's pagination walk (default
    2000): if walking exceeds it, _walk_listing_pagination stops and logs a
    warning rather than continuing silently. Curation used to implicitly
    bound scope by only ever seeding known-good listings; with curation gone
    this is the automatic backstop against a fingerprinting bug re-walking an
    unbounded shared catalog.

    KNOWN LIMITATION (found 2026-07-26, not fixed): the fingerprint is keyed
    on exact item-URL-set identity, not "is this the same underlying view
    reached a different way." Two URL paths that alias the identical view
    hash differently and each get fully walked - confirmed on letsmove,
    where /blog/all and /blog/all/all render the same content (same item
    set, same pager hash tokens) but produce different fingerprints, so both
    got independently walked in full. Confirmed low-impact where seen so
    far: Scrapy's own URL-level dupefilter still collapses the actual
    content items regardless of which pagination path found them, so this
    only wastes some redundant pagination requests, not final content-count
    accuracy - but worth fixing (e.g. checking response.url against a set of
    already-walked *entry* URLs too, not just the item-set fingerprint)
    before relying on this against a site where that pattern could be more
    costly.

    In all cases, no link inside the matched container is ever followed via
    parse_nav's own ordinary link-following loop - item links and
    pager/filter controls alike - only ever via the dedicated walk above.
    Links elsewhere on the same page are still followed normally (and, so
    are a .view container's own links when no pager is present - it's just
    an ordinary embedded widget, not a listing). The default (None for both
    LISTING_VIEW_LINK_EXTRACTOR/LISTING_PAGER_SELECTOR) leaves parse_nav's
    behavior exactly as before for subclasses that don't set them.

    Subclasses that set LISTING_VIEW_LINK_EXTRACTOR/LISTING_PAGER_SELECTOR
    must also implement _listing_pagination_items (return this page's item
    hrefs, template-specific) and _listing_pagination_next_url (return the
    next pagination page's href, or None) - see _walk_listing_pagination.

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

    # Subclasses that need a different depth can override custom_settings
    # entirely, but keep CRAWLSPIDER_FOLLOW_LINKS: False if they do.
    # CrawlSpider's own built-in _requests_to_follow runs unconditionally for
    # every start_urls response (triggered by _parse()'s hardcoded
    # follow=True), entirely independent of parse_nav/parse_start_url - it
    # extracts links via each Rule's LinkExtractor and applies only
    # rule.process_links, bypassing _filter_web_urls and
    # LISTING_VIEW_LINK_EXTRACTOR entirely. Confirmed empirically: a listing
    # page placed directly in start_urls leaks both its pager link and its
    # .view container's item links into the crawl via this path, even though
    # parse_nav's own manual loop correctly excludes both - undermining the
    # fan-out protection specifically for start_urls entries. Every
    # subsequent hop is unaffected (reached via this mixin's own
    # response.follow(..., callback=self.parse_nav) calls, a plain Request
    # with no CrawlSpider follow-machinery involvement), so this only ever
    # matters for start_urls, but disabling it entirely costs nothing since
    # parse_nav's manual loop is a complete replacement.
    custom_settings = {
        'DEPTH_LIMIT': 2,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
    }

    # Optional per-subclass hooks, both required together: a LinkExtractor
    # scoped to the container a listing's pagination/filter controls live
    # in, AND a CSS selector matching only when a real pager is present. See
    # "Automatic listing discovery, walk, and dedup" above. None (the
    # default) disables the feature.
    LISTING_VIEW_LINK_EXTRACTOR = None
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
                "listing_file is required. Run the companion *_harvest_list spider "
                "first, then pass its output: -a listing_file=data/mysite_harvest_list.csv"
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
        """sha1 of the sorted item-URL set extracted from a listing's
        container, as first encountered. Two listing pages that render the
        exact same item set (e.g. every video permalink's embedded "browse
        other videos" catalog) hash identically regardless of which
        textually-distinct URL each copy lives at - see "Automatic listing
        discovery, walk, and dedup" above."""
        digest = hashlib.sha1()
        for url in sorted(view_urls):
            digest.update(url.encode('utf-8'))
            digest.update(b'\n')
        return digest.hexdigest()

    def parse_nav(self, response):
        """Yield the URL and follow links if this is a nav content page.

        Pages in listing_file (already known listing URLs) are dropped
        entirely — no item yielded and no links followed. This prevents the
        spider from fanning out into known listing sections and their
        thousands of content URLs.

        Pages matched by LISTING_VIEW_LINK_EXTRACTOR are yielded, flagged via
        is_listing/depth, and their item-URL set fingerprinted - see
        "Automatic listing discovery, walk, and dedup" above for the full
        walk/dedup mechanism. No link inside the matched container is
        followed via the ordinary loop below — items and pager/filter
        controls alike; other links on the page are followed normally.

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
        if self.LISTING_VIEW_LINK_EXTRACTOR is not None and self.LISTING_PAGER_SELECTOR is not None:
            if response.css(self.LISTING_PAGER_SELECTOR):
                view_urls = {lnk.url for lnk in self.LISTING_VIEW_LINK_EXTRACTOR.extract_links(response)}
        yield {
            'url': response.url,
            'is_listing': bool(view_urls),
            'depth': response.request.meta.get('depth', 0) if response.request else 0,
        }
        self._census_links(response)
        if view_urls and response.url not in self.FORCE_SKIP_LISTING_URLS:
            # Fingerprint the clean, template-specific item set
            # (_listing_pagination_items), NOT view_urls - view_urls comes
            # from LISTING_VIEW_LINK_EXTRACTOR's wide .view-container scan,
            # which also picks up the container's own numbered pager links
            # (e.g. a Drupal pager rendering nearby page numbers, not just a
            # single "next" arrow). Those pager links point back to THIS
            # permalink's own URL, so every permalink's view_urls differs
            # even when the real catalog items are byte-identical -
            # confirmed empirically: two photogallery permalinks sharing the
            # exact same 8-item catalog hashed to different view_urls
            # fingerprints (16 raw links each, 8 of them self-referential
            # index__q_page=N.html pager links unique to that permalink) but
            # the identical fingerprint once computed from
            # _listing_pagination_items alone. Using the contaminated
            # view_urls set here would silently defeat the entire dedup
            # mechanism - the exact fan-out failure mode this was built to
            # prevent.
            item_urls = {response.urljoin(href) for href in self._listing_pagination_items(response)}
            # Register before walking, not after - avoids a race where two
            # near-simultaneous discoveries of the same shared catalog both
            # start walking before either finishes.
            fingerprint = self._listing_fingerprint(item_urls)
            if fingerprint not in self._seen_listing_fingerprints:
                self._seen_listing_fingerprints.add(fingerprint)
                yield from self._walk_listing_pagination(response, _skip_census=True)
        for rule in self._rules:
            links = self._apply_nav_deny(self._filter_web_urls(rule.link_extractor.extract_links(response)))
            for link in links:
                if link.url in view_urls:
                    continue
                yield response.follow(link.url, callback=self.parse_nav)

    # CrawlSpider routes each start_urls response through parse_start_url
    # instead of the Rule's callback, so without this override a listing
    # page placed directly in start_urls would bypass _is_listing_page and
    # LISTING_VIEW_LINK_EXTRACTOR entirely on its first fetch - fanning out
    # into its full item/pager range unfiltered. Delegating unifies the two
    # entry points onto identical logic.
    parse_start_url = parse_nav

    def _listing_pagination_items(self, response):
        """Return this listing pagination page's item hrefs (template-
        specific CSS/xpath, e.g. '.views-row h2 a::attr(href)'). Required
        override for any subclass that sets LISTING_VIEW_LINK_EXTRACTOR/
        LISTING_PAGER_SELECTOR - see _walk_listing_pagination."""
        raise NotImplementedError(
            f'{type(self).__name__} sets LISTING_VIEW_LINK_EXTRACTOR/'
            'LISTING_PAGER_SELECTOR but does not implement '
            '_listing_pagination_items'
        )

    def _listing_pagination_next_url(self, response):
        """Return this listing pagination page's next-page href, or None if
        this is the last page. Required override alongside
        _listing_pagination_items - see _walk_listing_pagination."""
        raise NotImplementedError(
            f'{type(self).__name__} sets LISTING_VIEW_LINK_EXTRACTOR/'
            'LISTING_PAGER_SELECTOR but does not implement '
            '_listing_pagination_next_url'
        )

    def _walk_listing_pagination(self, response, _page_count=1, _skip_census=False):
        """Walk a listing's full pagination automatically, fetching each
        extracted item through parse_nav (rather than merely recording its
        URL) so the item's own outbound links get explored too - see
        "Automatic listing discovery, walk, and dedup" above. Recurses
        through subsequent pages via this same callback; only the entry
        page's fingerprint gets checked (in parse_nav) - a fresh fingerprint
        check per pagination page isn't needed since the whole chain is only
        ever reached once, from that one fingerprint-gated call.

        _skip_census avoids double-logging the entry page's census (parse_nav
        already ran it on that same response before dispatching here) without
        skipping it for every later page in the chain, which never go through
        parse_nav at all.
        """
        rules = self._get_exclusion_rules()
        for href in self._listing_pagination_items(response):
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
                'Listing pagination at %s hit LISTING_MAX_PAGES=%d without '
                'reaching its last page - aborting walk. Possible '
                'fingerprinting failure to collapse a shared/duplicate '
                'catalog; investigate before trusting this listing\'s '
                'harvested items.',
                response.url, self.LISTING_MAX_PAGES,
            )
            return

        next_href = self._listing_pagination_next_url(response)
        if next_href:
            yield response.follow(
                next_href, callback=self._walk_listing_pagination,
                cb_kwargs={'_page_count': _page_count + 1},
            )


class ArchiveSpiderMixin(ExclusionLoggingMixin):
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
        text = re.sub(r'([\W_])\1{2,} ?', '', text)
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
