import csv
import hashlib
import re

import scrapy

from archive_crawler import exclusion_rules as _exclusion_rules_module
from archive_crawler.items import HarvestItem
from archive_crawler.spiders.exclusion_logging import ExclusionLoggingMixin

# Drupal Views always emits these two classes on a view's own wrapper
# element, in this fixed order, before any theme-added extra class that
# happens to share the same prefix (e.g. a suffixed view-display-id-page_1
# -most-recent following the canonical view-display-id-page_1) - see
# NavHarvesterMixin._view_identity.
_VIEW_ID_RE = re.compile(r'^view-id-(.+)$')
_VIEW_DISPLAY_ID_RE = re.compile(r'^view-display-id-(.+)$')


class NavHarvesterMixin(ExclusionLoggingMixin):
    r"""Mixin for CrawlSpider-based nav harvesters.

    Provides listing-file exclusion, web-page URL filtering, and a parse_nav
    callback. Subclasses supply name, allowed_domains, start_urls, and rules.

    See HARVESTING.md for the full end-to-end process this mixin fits into,
    and ARCHITECTURE.md for the full listing-fingerprint mechanism design
    (how listing detection, fingerprinting, and pagination-walking fit
    together), its known limitations, and the decision rule for whether to
    enable it on a given site.

    listing_file is required
    ------------------------
    Every nav harvester must be given a dedup set of already-known content
    URLs via -a listing_file=<path> (a CSV with a url column; an empty file -
    header row only - is fine on a first run). A URL in that file is treated
    as already-known good content, so the nav crawler must not re-fetch,
    re-emit, or re-follow it.

    If a site is simple enough that a listing_file is unnecessary, it does
    not need this mixin at all — use generic_crawl_harvest instead.

    Subclass contract
    ------------------
    Three class attributes, required together (default: None, which
    disables listing-fingerprint dedup entirely - parse_nav then follows
    every link on the page unconditionally):

    - LISTING_VIEW_LINK_EXTRACTOR: a LinkExtractor scoped to the container a
      listing's item rows and pager share, e.g.
      LinkExtractor(restrict_css='.view') for Drupal Views.
    - LISTING_CONTAINER_SELECTOR: a plain CSS selector string for that same
      container, e.g. '.view'.
    - LISTING_PAGER_SELECTOR: a CSS selector that matches only when a real,
      populated pager is present, e.g. '.pager-current'.

    Two required method overrides, if the three attributes above are set -
    both take a single Selector scoped to one container, not the full
    response (see ARCHITECTURE.md for why):

    - _listing_pagination_items(container): this container's item hrefs.
    - _listing_pagination_next_url(container): this container's next
      pagination page's href, or None on the last page.

    Usage:
        # listing_file is required even on a first run - point it at an
        # empty CSV (header row only) when there's no prior harvest to seed
        # it with:
        #   echo "url" > data/mysite_empty-listing.csv
        #
        #   scrapy crawl mysite_harvest \
        #       -a listing_file=data/mysite_empty-listing.csv \
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
    # "Subclass contract" above. None (the default) disables the feature.
    LISTING_VIEW_LINK_EXTRACTOR = None
    LISTING_CONTAINER_SELECTOR = None
    LISTING_PAGER_SELECTOR = None

    # Escape hatch: a URL in this set is always flagged is_listing and never
    # auto-walked, regardless of its fingerprint. Empty by default and not
    # required for normal operation - see ARCHITECTURE.md.
    FORCE_SKIP_LISTING_URLS = frozenset()

    # Defense-in-depth cap on a single listing's pagination walk. See
    # ARCHITECTURE.md.
    LISTING_MAX_PAGES = 2000

    # Distinct from ArchiveSpiderMixin's default 'exclusions' - a nav
    # harvester and its companion content spider share the same SOURCE_SITE,
    # so writing to the same filename would have one overwrite the other's
    # log whenever both run against the same site.
    EXCLUSIONS_FILE_SUFFIX = 'nav-exclusions'

    # Extension point: a subclass that also composes ArchiveSpiderMixin and
    # defines its own _scrape_item(self, response) gets content extraction
    # inline on the same response fetched for nav discovery (see
    # _maybe_scrape_item below). None (the default) keeps a subclass
    # harvest-only.
    _scrape_item = None

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
        # In-memory only, built up over one crawl run - see "Subclass
        # contract" above.
        self._seen_listing_fingerprints = set()

    def start_requests(self):
        """CrawlSpider has no start_requests of its own - it relies on the
        plain scrapy.Spider default (one Request per start_urls entry,
        routed to parse_start_url via CrawlSpider._parse). Explicit
        override, called directly rather than via super(), because a
        subclass that also composes ArchiveSpiderMixin would otherwise
        inherit ITS start_requests (reads url_file - a different spider
        shape entirely) ahead of scrapy.Spider's in MRO."""
        return scrapy.Spider.start_requests(self)

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
        Scoped to rules:/nav_deny matches only - not _is_already_known_url's
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

    def _is_already_known_url(self, response):
        """Return True if this URL should be skipped entirely because
        listing_file already has it as known content.

        Kept as an overridable hook in case a subclass ever needs a
        genuinely different skip condition, but do not add CSS-based
        listing detection here - use LISTING_VIEW_LINK_EXTRACTOR (flag,
        don't exclude) instead. See "listing_file is required" above.
        """
        return response.url in self._listing_urls

    @staticmethod
    def _listing_fingerprint(view_urls):
        """sha1 of the sorted item-URL set extracted from one listing
        container, as first encountered. Two listing pages that render the
        exact same item set (e.g. every video permalink's embedded "browse
        other videos" catalog) hash identically regardless of which
        textually-distinct URL each copy lives at - see "Subclass contract"
        above. Combined with _view_identity into a composite key by
        parse_nav - this hash alone is not the dedup key."""
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

        Delegates to three phases, in order, each doing one part of what
        used to be a single ~70-line function - see ARCHITECTURE.md for the
        full listing-fingerprint mechanism these phases implement:

        1. _detect_listing_containers - find every LISTING_CONTAINER_SELECTOR
           match on the page with a populated pager.
        2. _walk_new_listings - fingerprint each and walk its pagination the
           first time that fingerprint is seen this run.
        3. _follow_ordinary_links - follow every other non-excluded link on
           the page (skipping links already pooled into a matched listing
           container).

        Links are followed manually (rather than via follow=True in the
        Rule) so that we can gate following on these per-page checks.
        Subclass rules must set follow=False and omit process_links - the
        latter would be dead configuration, since CRAWLSPIDER_FOLLOW_LINKS:
        False in custom_settings means CrawlSpider's own Rule-dispatch
        machinery (which calls rule.process_links) never runs.

        The web-URL guard is applied to response.url as well as to
        extracted links because start_urls entries reach this callback (via
        parse_start_url) without ever passing through _filter_web_urls -
        that only runs on links extracted from an already-fetched response,
        not on the seed URLs themselves.
        """
        if not _exclusion_rules_module.is_web_url(response.url, self._get_exclusion_rules()):
            return
        if self._is_already_known_url(response):
            return
        listing_containers, view_urls = self._detect_listing_containers(response)
        yield HarvestItem(
            url=response.url,
            is_listing=bool(listing_containers),
            depth=response.request.meta.get('depth', 0) if response.request else 0,
        )
        self._census_links(response)
        yield from self._walk_new_listings(response, listing_containers)
        if not listing_containers:
            yield from self._maybe_scrape_item(response)
        yield from self._follow_ordinary_links(response, view_urls)

    def _detect_listing_containers(self, response):
        """Return (listing_containers, view_urls) for this page.

        listing_containers is a list of (index, container Selector) pairs,
        one per LISTING_CONTAINER_SELECTOR match that has a populated
        LISTING_PAGER_SELECTOR inside it - evaluated independently per
        container, since a page can carry more than one genuinely paginated
        listing (confirmed, e.g. obamawhitehouse's /energy/news, which
        renders two independently-paginated Views blocks side by side).

        view_urls is the wider set LISTING_VIEW_LINK_EXTRACTOR itself
        returns (item links AND the container's own numbered pager links) -
        used by _follow_ordinary_links to avoid double-following, not for
        fingerprinting (see _listing_fingerprint's own docstring for why
        that uses _listing_pagination_items instead).

        Both are empty if any of the three LISTING_* attributes is unset -
        the default, which disables listing-awareness entirely.
        """
        if (self.LISTING_VIEW_LINK_EXTRACTOR is None
                or self.LISTING_CONTAINER_SELECTOR is None
                or self.LISTING_PAGER_SELECTOR is None):
            return [], set()
        containers = response.css(self.LISTING_CONTAINER_SELECTOR)
        listing_containers = [
            (index, container) for index, container in enumerate(containers)
            if container.css(self.LISTING_PAGER_SELECTOR)
        ]
        view_urls = set()
        if listing_containers:
            view_urls = {lnk.url for lnk in self.LISTING_VIEW_LINK_EXTRACTOR.extract_links(response)}
        return listing_containers, view_urls

    def _walk_new_listings(self, response, listing_containers):
        """Fingerprint each detected container and walk its pagination the
        first time that (view_id, display_id, item_hash) key is seen this
        run - see _listing_fingerprint and _view_identity. A key already in
        self._seen_listing_fingerprints is skipped entirely: that container
        was already flagged is_listing by _detect_listing_containers/
        parse_nav, and nothing inside it gets walked or followed twice.

        response.url in FORCE_SKIP_LISTING_URLS short-circuits the whole
        page - the escape hatch for a listing confirmed to need manual
        exclusion from auto-walking regardless of its fingerprint.
        """
        if response.url in self.FORCE_SKIP_LISTING_URLS:
            return
        for index, container in listing_containers:
            # Fingerprint _listing_pagination_items, NOT view_urls - the
            # latter also includes the container's own numbered pager
            # links, which point back to THIS permalink's own URL and so
            # differ per permalink even for a byte-identical catalog (see
            # _listing_fingerprint's own docstring).
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

    def _follow_ordinary_links(self, response, view_urls):
        """Follow every link this page's rules extract, except one already
        pooled into a matched listing container (view_urls) - those are
        only ever followed via _walk_new_listings' dedicated walk, never
        through this ordinary loop (see the mixin's docstring)."""
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
        NavHarvesterMixin (e.g. a new site explored before its
        content-extraction selectors are written) shares this parse_nav
        unchanged and stays harvest-only. A subclass that also defines
        _scrape_item (e.g. letsmove.py, obama_whitehouse.py) extracts
        content inline on the same response already fetched for nav
        discovery - no second fetch."""
        if self._scrape_item is None:
            return
        item = self._scrape_item(response)
        if item is not None:
            yield item

    # CrawlSpider routes each start_urls response through parse_start_url
    # instead of the Rule's callback, so without this override a listing
    # page placed directly in start_urls would bypass _is_already_known_url
    # and LISTING_VIEW_LINK_EXTRACTOR entirely on its first fetch - fanning
    # out into its full item/pager range unfiltered. Delegating unifies the
    # two entry points onto identical logic.
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
        - see "Subclass contract" above. Recurses through subsequent pages
        via this same callback; only the entry page's fingerprint gets
        checked (in _walk_new_listings) - a fresh fingerprint check per
        pagination page isn't needed since the whole chain is only ever
        reached once, from that one fingerprint-gated call.

        container_index/view_id/display_id identify which of this page's
        LISTING_CONTAINER_SELECTOR matches to operate on - re-selected fresh
        via _select_container on every pagination page fetched through this
        method's own recursive response.follow(...,
        cb_kwargs={'container_index': ..., 'view_id': ..., 'display_id':
        ...}) call, not carried over as a Selector object across requests
        (a Selector is scoped to the response it came from, so a later
        page's container has to be re-selected from that page's own
        response regardless).

        _skip_census avoids double-logging the entry page's census
        (_walk_new_listings' caller already ran it on that same response
        before dispatching here) without skipping it for every later page
        in the chain, which never go through parse_nav at all.
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
