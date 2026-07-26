from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class ObamaWhiteHouseHarvestSpider(NavHarvesterMixin, CrawlSpider):
    """Unified nav+listing discovery pass, replacing the separate
    obama_whitehouse_harvest_nav/_list spiders and merge_harvest.py's
    reconciliation step for this site. Still URL-discovery only (no content
    extraction) - the content spider (obama_whitehouse.py) remains a
    separate, later, explicitly-gated stage.

    Why unify: nav's own ordinary link-following (DEPTH_LIMIT=20, BFS) was
    already proven to reach full graph closure from the homepage alone
    (zero depth-exceeded ignores in prior runs) - the only thing it
    deliberately never does is follow into a flagged listing's own .view
    container (item rows + pager), to avoid fanning out into a listing's
    full item/pagination range during ordinary graph traversal. That
    container-skip is the actual load-bearing protection this whole split
    ever needed, not depth limitation, which nav alone already handles
    (raising DEPTH_LIMIT from 2 to 20 already made a large curated
    start_urls list unnecessary for nav's own coverage). Running two
    separate spider processes - nav discovering + flagging listings,
    listing separately walking a manually-promoted seed list, then
    merge_harvest.py reconciling the two output files - added a slow
    human-curation step between discovery and walking, and forced the
    content spider to grow its own belated not_in_seed_list check to catch
    whatever the two-pass model missed.

    Listing discovery and pagination-walking are now both fully automatic,
    via NavHarvesterMixin's fingerprint mechanism (see that mixin's own
    docstring) - no curated seed list. This still keeps the exact same
    fan-out protection the old LISTING_SEEDS-gated design had: every
    /photos-and-video/{video,photogallery}/* permalink embeds the *same*
    sitewide "browse other videos/galleries" catalog (confirmed via diffing
    item lists across multiple unrelated permalinks - byte identical, ~5,920
    videos across 740 pages for the video template alone), so the first
    permalink encountered walks the catalog once and every subsequent
    permalink's identical item set hashes to the same fingerprint and is
    flagged-and-skipped, never re-walked.
    """

    name = "obama_whitehouse_harvest"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'www.obamawhitehouse'
    # Distinct from the old 'nav-exclusions'/'listing-exclusions' pair (both
    # remain on disk as historical reference, not overwritten) - this is one
    # unified exclusion log for the merged spider.
    EXCLUSIONS_FILE_SUFFIX = 'harvest-exclusions'

    # .view is Drupal Views' own wrapper and reliably encloses both a
    # listing's item rows and its pager/filter controls, confirmed across
    # two distinct templates (teaser-card blog/author listings and the
    # table-based photo/video gallery view both render inside a .view div).
    # .view presence ALONE is not enough, though - ordinary topic/content
    # pages that merely embed a "related videos"/"related blog posts" widget
    # also render inside a .view container with real links, but carry no
    # pager (confirmed: /issues/education/k-12 and the Cairo speech page
    # both do this). LISTING_PAGER_SELECTOR requires an actual populated
    # pager - .pager-current, confirmed present on both real listing
    # templates - before a page counts as a listing at all.
    # deny_extensions=() disables Scrapy's own built-in IGNORED_EXTENSIONS
    # denylist (pdf/doc/zip/jpg/etc.) so our own is_web_url allow-list
    # (archive_crawler/exclusion_rules/<site>.yml) is the sole authority on
    # what counts as a web page.
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['obamawhitehouse.archives.gov'],
        deny_extensions=(),
    )
    LISTING_PAGER_SELECTOR = '.pager-current'

    # DEPTH_LIMIT raised well past the mixin's usual 20 to comfortably clear
    # the longest known curated-listing pagination chain
    # (briefing-room/statements-and-releases, 1,176 pages). Scrapy's
    # DepthMiddleware counts every response.follow() call toward one shared
    # depth counter regardless of which callback issued it - confirmed by
    # reading DepthMiddleware._filter directly, it computes
    # request.meta['depth'] from the CURRENT response's own depth with no
    # way to reset/exempt a specific chain - so _walk_listing_pagination's
    # own pager-following would otherwise get silently killed around page 20
    # instead of reaching each section's true end.
    #
    # Safe to raise this high: nav's own ordinary link-following is
    # independently proven to reach full graph closure by depth 19
    # regardless of the ceiling (zero depth-exceeded ignores at
    # DEPTH_LIMIT=20 in prior runs, i.e. nothing reachable via ordinary
    # links sits anywhere near this new ceiling anyway). The
    # video/photogallery fan-out protection (the fingerprint dedup in
    # NavHarvesterMixin.parse_nav) is a separate, content-based mechanism
    # independent of DEPTH_LIMIT, so raising this ceiling does not reopen
    # that risk for any duplicate-catalog permalink nav wanders into during
    # ordinary traversal - those still only ever get flagged is_listing=True
    # and skipped, never re-walked, once their fingerprint is already known.
    #
    # FEED_EXPORT_FIELDS declared explicitly so the CSV header doesn't
    # depend on whichever item happens to export first - harmless now that
    # every yielded item shares the same url+is_listing+depth shape, but
    # kept for explicitness against Scrapy's CsvItemExporter otherwise
    # inferring fields_to_export from the first item's own keys alone.
    custom_settings = {
        'DEPTH_LIMIT': 1300,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEED_EXPORT_FIELDS': ['url', 'is_listing', 'depth'],
    }

    start_urls = ['https://obamawhitehouse.archives.gov/']

    rules = (
        Rule(
            # allow= anchors to the exact hostname; allow_domains alone would
            # also match subdomains like letsmove.obamawhitehouse.archives.gov.
            LinkExtractor(
                allow=r'//obamawhitehouse\.archives\.gov/',
                allow_domains=['obamawhitehouse.archives.gov'],
                deny_extensions=(),
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav, only from non-listing pages
        ),
    )

    # Three known listing templates: teaser-card (.views-row h2/h3 a, e.g.
    # blog/author pages), table-based gallery (.views-field-title, e.g.
    # photo/video galleries), and person-directory (.views-row
    # .views-field-nid a, e.g. /blog/authors).
    def _listing_pagination_items(self, response):
        links = response.css(
            '.views-row h2 a::attr(href), .views-row h3 a::attr(href)'
        ).getall()
        if not links:
            links = response.css('.views-field-title a::attr(href)').getall()
        if not links:
            links = response.css('.views-row .views-field-nid a::attr(href)').getall()
        return links

    # .pager-current's immediately-following sibling <li> holds the forward
    # link in both templates (a "Next" link in the teaser-card pager, a
    # numbered page link in the gallery pager) - one selector covers both
    # rather than branching on .pager-next (which the gallery template
    # doesn't use at all).
    def _listing_pagination_next_url(self, response):
        return response.css('.pager-current + li a::attr(href)').get()
