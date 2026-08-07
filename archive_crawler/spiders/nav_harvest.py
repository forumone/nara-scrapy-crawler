import hashlib
import re

import scrapy

from archive_crawler import exclusion_rules as _exclusion_rules_module
from archive_crawler.items import HarvestItem
from archive_crawler.spiders.exclusion_logging import ExclusionLoggingMixin

# Drupal Views emits these two classes on a view's wrapper element before
# any theme-added extra class sharing the same prefix - see
# NavHarvesterMixin._view_identity.
_VIEW_ID_RE = re.compile(r'^view-id-(.+)$')
_VIEW_DISPLAY_ID_RE = re.compile(r'^view-display-id-(.+)$')


class NavHarvesterMixin(ExclusionLoggingMixin):
    r"""Mixin for CrawlSpider-based nav harvesters.

    Provides web-page URL filtering and a parse_nav callback. Subclasses
    supply name, allowed_domains, start_urls, and rules.

    See HARVESTING.md for the end-to-end process this mixin fits into,
    and ARCHITECTURE.md for the listing-fingerprint mechanism, its
    limitations, and when to enable it.

    Every crawl starts fresh - no dedup against a prior run's output. A
    recrawl re-fetches, re-scrapes, and re-emits every URL the site
    currently exposes, fully superseding the old CSV.

    Subclass contract
    ------------------
    Three class attributes, required together (default: None, which
    disables listing-fingerprint dedup - parse_nav then follows every
    link unconditionally):

    - LISTING_VIEW_LINK_EXTRACTOR: a LinkExtractor scoped to the container a
      listing's item rows and pager share, e.g.
      LinkExtractor(restrict_css='.view') for Drupal Views.
    - LISTING_CONTAINER_SELECTOR: a plain CSS selector for that same
      container, e.g. '.view'.
    - LISTING_PAGER_SELECTOR: a CSS selector matching only when a real,
      populated pager is present, e.g. '.pager-current'.

    Two required method overrides if the three attributes above are set -
    both take a single Selector scoped to one container, not the full
    response (see ARCHITECTURE.md for why):

    - _listing_pagination_items(container): this container's item hrefs.
    - _listing_pagination_next_url(container): this container's next
      pagination page's href, or None on the last page.

    Usage:
        #   scrapy crawl mysite_harvest -o data/mysite/mysite_harvest.csv

        class MySiteHarvestSpider(NavHarvesterMixin, CrawlSpider):
            name = "mysite_harvest"
            allowed_domains = ["example.com"]
            start_urls = [...]
            rules = (
                Rule(
                    # allow= anchors to the exact hostname; allow_domains
                    # alone also matches subdomains, usually handled by
                    # their own separate spider.
                    LinkExtractor(
                        allow=r'//example\.com/',
                        allow_domains=['example.com'],
                    ),
                    callback='parse_nav',
                    follow=False,  # links followed manually in parse_nav
                ),
            )
    """

    # Subclasses needing a different depth can override custom_settings,
    # but must keep CRAWLSPIDER_FOLLOW_LINKS: False - CrawlSpider's
    # built-in link-following runs unconditionally on every start_urls
    # response, bypassing _filter_web_urls/LISTING_VIEW_LINK_EXTRACTOR and
    # leaking listing/pager links that parse_nav's manual loop correctly
    # excludes.
    custom_settings = {
        'DEPTH_LIMIT': 2,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
    }

    # Optional per-subclass hooks, all three required together - see
    # "Subclass contract" above. None (default) disables the feature.
    LISTING_VIEW_LINK_EXTRACTOR = None
    LISTING_CONTAINER_SELECTOR = None
    LISTING_PAGER_SELECTOR = None

    # Escape hatch: a URL here is always flagged is_listing and never
    # auto-walked, regardless of fingerprint. See ARCHITECTURE.md.
    FORCE_SKIP_LISTING_URLS = frozenset()

    # Defense-in-depth cap on a single listing's pagination walk. See
    # ARCHITECTURE.md.
    LISTING_MAX_PAGES = 2000

    # Opt-in escape hatch: False (default) means a detected listing
    # container blocks scraping the page's own content entirely. Obama WH
    # is the confirmed exception - permalink pages under
    # /photos-and-video/{video,photogallery}/* embed a real, paginated
    # "browse other videos/galleries" widget as a sidebar, but the
    # permalink's own primary content is real and distinct. Setting this
    # True makes parse_nav attempt _maybe_scrape_item even when a listing
    # container is detected, falling back to logging listing_page only if
    # that attempt finds no body (see ObamaWhiteHouseSpider._scrape_item).
    # No other no-sitemap site has this template shape confirmed - leave
    # False unless one turns up.
    SCRAPE_DETECTED_LISTINGS = False

    # Extension point: a subclass that also composes ArchiveSpiderMixin
    # and defines its own _scrape_item(self, response) gets content
    # extraction inline on the response fetched for nav discovery. None
    # (default) keeps a subclass harvest-only.
    _scrape_item = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # In-memory only, built up over one crawl run - see "Subclass
        # contract" above.
        self._seen_listing_fingerprints = set()

    def start_requests(self):
        """Same as Spider's own default, except dont_filter=False.

        Spider.start_requests() hardcodes dont_filter=True, which skips
        recording the seed request's fingerprint as seen. For every site
        this mixin serves, start_urls is that site's own homepage -
        usually linked from elsewhere on the site - so the unrecorded
        seed request lets a later in-crawl link to the same URL slip past
        the dupefilter and get scraped twice. None of these spiders use
        JOBDIR-based resume (the usual reason dont_filter=True matters),
        so there's no downside to recording it normally."""
        for url in self.start_urls:
            yield scrapy.Request(url, dont_filter=False)

    def _strip_query_noise(self, links):
        """Mutate each link's .url in place, dropping utm_*-prefixed (and
        any site-configured query_params_deny) params. Done before
        _filter_web_urls/_apply_exclusion_rules/dedup so a
        tracking-decorated URL collapses onto its bare canonical form's
        own dupefilter fingerprint."""
        rules = self._get_exclusion_rules()
        for lnk in links:
            lnk.url = _exclusion_rules_module.strip_denied_query_params(lnk.url, rules)
        return links

    def _filter_web_urls(self, links):
        rules = self._get_exclusion_rules()
        return [lnk for lnk in links if _exclusion_rules_module.is_web_url(lnk.url, rules)]

    def _apply_exclusion_rules(self, links):
        """Drop links matching this domain's rules
        (archive_crawler/exclusion_rules/<SOURCE_SITE>.yml).

        Called directly from parse_nav's manual link-following loop, not
        via a Rule's process_links= - CRAWLSPIDER_FOLLOW_LINKS is False
        specifically so CrawlSpider's own Rule-dispatch never runs. Don't
        wire this as process_links= in a subclass; that codepath never
        executes.

        Every dropped link is logged via _log_exclusion: these come from
        the crawl's own real link-following, so a rules: match here is a
        genuine per-rule exclusion the client's audit needs. Scoped to
        rules: matches only, not _filter_web_urls' non-web-URL filtering
        (high volume, not useful signal)."""
        rules = self._get_exclusion_rules()
        kept = []
        for lnk in links:
            reason = _exclusion_rules_module.match_exclude(lnk.url, rules)
            if reason is not None:
                self._log_exclusion(lnk.url, reason)
                continue
            kept.append(lnk)
        return kept

    @staticmethod
    def _listing_fingerprint(view_urls):
        """sha1 of the sorted item-URL set from one listing container.
        Two listing pages rendering the exact same item set (e.g. every
        video permalink's embedded "browse other videos" catalog) hash
        identically regardless of which URL each copy lives at. Combined
        with _view_identity into parse_nav's composite dedup key - this
        hash alone is not the key."""
        digest = hashlib.sha1()
        for url in sorted(view_urls):
            digest.update(url.encode('utf-8'))
            digest.update(b'\n')
        return digest.hexdigest()

    @staticmethod
    def _view_identity(container):
        """Return (view_id, display_id) parsed from a Drupal Views
        container's class attribute (view-id-<name>,
        view-display-id-<id>), or (None, None) if absent. Takes the
        first matching class token - Drupal always emits the canonical
        classes before any theme-added extra class sharing the prefix.
        Used by parse_nav to distinguish coinciding item sets, and by
        _select_container to re-locate the same container across a
        listing's pagination pages."""
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

        Delegates to three phases, in order - see ARCHITECTURE.md for the
        full mechanism:

        1. _detect_listing_containers - find every LISTING_CONTAINER_SELECTOR
           match with a populated pager.
        2. _walk_new_listings - fingerprint each and walk its pagination
           the first time that fingerprint is seen this run.
        3. _follow_ordinary_links - follow every other non-excluded link
           (skipping links already pooled into a matched listing
           container).

        Links are followed manually, not via follow=True in the Rule, so
        following can be gated on these per-page checks. Subclass rules
        must set follow=False and omit process_links (see
        _apply_exclusion_rules for why the latter would be dead
        configuration).

        The web-URL guard is applied to response.url as well as to
        extracted links, since start_urls entries reach this callback
        without passing through _filter_web_urls.

        Both remaining checks below guard the whole method: a URL with no
        extension hinting at its content type (e.g. a JSON API endpoint)
        can reach here despite is_web_url's extension check, since that
        only inspects the URL, not the response - a plain binary Response
        has no .css()/.selector at all (caught by the isinstance check),
        while a JSON TextResponse gets a dict selector root instead of an
        lxml tree (caught by the selector.type check).
        """
        if not _exclusion_rules_module.is_web_url(response.url, self._get_exclusion_rules()):
            return
        depth = response.request.meta.get('depth', 0) if response.request else 0
        if not isinstance(response, scrapy.http.TextResponse):
            yield HarvestItem(url=response.url, is_listing=False, depth=depth)
            self._log_dropped(response.url, 'non_text_response')
            return
        if response.selector.type == 'json':
            yield HarvestItem(url=response.url, is_listing=False, depth=depth)
            self._log_dropped(response.url, 'non_text_response')
            return
        listing_containers, view_urls = self._detect_listing_containers(response)
        yield HarvestItem(
            url=response.url,
            is_listing=bool(listing_containers),
            depth=depth,
        )
        yield from self._walk_new_listings(response, listing_containers)
        if listing_containers:
            # A listing page's own content isn't scraped unless this
            # subclass opts into SCRAPE_DETECTED_LISTINGS and the scrape
            # attempt finds something. Logging listing_page when it
            # doesn't means the row stays accounted for - scrape + drop =
            # harvest holds for every row yielded here.
            scraped = list(self._maybe_scrape_item(response)) if self.SCRAPE_DETECTED_LISTINGS else []
            if scraped:
                yield from scraped
            else:
                self._log_dropped(response.url, 'listing_page')
        else:
            yield from self._maybe_scrape_item(response)
        yield from self._follow_ordinary_links(response, view_urls)

    def _detect_listing_containers(self, response):
        """Return (listing_containers, view_urls) for this page.

        listing_containers is a list of (index, container Selector)
        pairs, one per LISTING_CONTAINER_SELECTOR match with a populated
        LISTING_PAGER_SELECTOR inside it - evaluated per container, since
        a page can carry more than one genuinely paginated listing
        (confirmed on obamawhitehouse's /energy/news).

        view_urls is the wider set LISTING_VIEW_LINK_EXTRACTOR returns
        (item links AND the container's own pager links) - used by
        _follow_ordinary_links to avoid double-following, not for
        fingerprinting (see _listing_fingerprint).

        Both are empty if any of the three LISTING_* attributes is
        unset."""
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
        """Fingerprint each detected container and walk its pagination
        the first time that (view_id, display_id, item_hash) key is seen
        this run - see _listing_fingerprint and _view_identity. A key
        already in self._seen_listing_fingerprints is skipped - that
        container was already flagged is_listing and nothing inside it
        gets walked or followed twice.

        response.url in FORCE_SKIP_LISTING_URLS short-circuits the whole
        page."""
        if response.url in self.FORCE_SKIP_LISTING_URLS:
            return
        for index, container in listing_containers:
            # Fingerprint _listing_pagination_items, NOT view_urls - the
            # latter includes the container's own pager links, which
            # differ per permalink even for a byte-identical catalog.
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
                display_id=display_id,
            )

    def _follow_ordinary_links(self, response, view_urls):
        """Follow every link this page's rules extract, except one
        already pooled into a matched listing container (view_urls) -
        those are only followed via _walk_new_listings' own walk."""
        for rule in self._rules:
            links = self._strip_query_noise(rule.link_extractor.extract_links(response))
            links = self._apply_exclusion_rules(self._filter_web_urls(links))
            for link in links:
                if link.url in view_urls:
                    continue
                yield response.follow(link.url, callback=self.parse_nav)

    def _maybe_scrape_item(self, response):
        """No-op unless a subclass also composes ArchiveSpiderMixin and
        defines _scrape_item. A subclass composing only NavHarvesterMixin
        stays harvest-only. A subclass that defines _scrape_item (e.g.
        letsmove.py, obama_whitehouse.py) extracts content inline on the
        same response already fetched for nav discovery."""
        if self._scrape_item is None:
            return
        item = self._scrape_item(response)
        if item is not None:
            yield item

    # CrawlSpider routes each start_urls response through parse_start_url
    # instead of the Rule's callback - without this override a listing
    # page in start_urls would bypass LISTING_VIEW_LINK_EXTRACTOR on its
    # first fetch.
    parse_start_url = parse_nav

    def _listing_pagination_items(self, container):
        """Return this listing container's item hrefs (template-specific
        CSS/xpath), scoped to the container Selector parse_nav passes in.
        Required override for any subclass setting
        LISTING_VIEW_LINK_EXTRACTOR/LISTING_CONTAINER_SELECTOR/
        LISTING_PAGER_SELECTOR."""
        raise NotImplementedError(
            f'{type(self).__name__} sets LISTING_VIEW_LINK_EXTRACTOR/'
            'LISTING_CONTAINER_SELECTOR/LISTING_PAGER_SELECTOR but does not '
            'implement _listing_pagination_items'
        )

    def _listing_pagination_next_url(self, container):
        """Return this listing container's next-page href, or None on
        the last page. Scoped the same as _listing_pagination_items;
        required alongside it."""
        raise NotImplementedError(
            f'{type(self).__name__} sets LISTING_VIEW_LINK_EXTRACTOR/'
            'LISTING_CONTAINER_SELECTOR/LISTING_PAGER_SELECTOR but does not '
            'implement _listing_pagination_next_url'
        )

    def _select_container(self, response, container_index, view_id, display_id):
        """Re-locate 'the same' listing container on a later pagination
        page. Prefers matching by the container's Drupal
        view-id/view-display-id (stable across pagination - view-dom-id
        is what's randomized per-request, not this), falling back to
        positional index if no container's identity matches (e.g. a
        non-Drupal site, or shape changed between pages). Positional
        fallback assumes container order is stable across pages - true
        in practice but not guaranteed, hence preferring identity
        first."""
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
        _page_count=1,
    ):
        """Walk one listing container's full pagination, fetching each
        item through parse_nav (not just recording its URL) so the
        item's own outbound links get explored too. Recurses through
        subsequent pages via this same callback; only the entry page's
        fingerprint gets checked (in _walk_new_listings) - the whole
        chain is only ever reached once, from that one gated call.

        container_index/view_id/display_id identify which container to
        operate on, re-selected fresh via _select_container on every
        pagination page (a Selector is scoped to the response it came
        from, so it can't be carried across requests).

        Guards against a non-HTML response the same way parse_nav does -
        registered as its own Scrapy callback, so it never goes through
        parse_nav's guard. Unlike parse_nav, no HarvestItem is yielded
        here even on success - a pagination-continuation URL never has
        its own harvest row, so scrape + drop = harvest is unaffected."""
        if not isinstance(response, scrapy.http.TextResponse):
            self._log_dropped(response.url, 'non_text_response')
            return
        if response.selector.type == 'json':
            self._log_dropped(response.url, 'non_text_response')
            return
        container = self._select_container(response, container_index, view_id, display_id)
        rules = self._get_exclusion_rules()
        for href in self._listing_pagination_items(container):
            url = _exclusion_rules_module.strip_denied_query_params(response.urljoin(href), rules)
            reason = _exclusion_rules_module.match_exclude(url, rules)
            if reason is not None:
                self._log_exclusion(url, reason)
                continue
            yield response.follow(url, callback=self.parse_nav)

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
