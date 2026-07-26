from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler import exclusion_rules
from archive_crawler.spiders.base import NavHarvesterMixin


class LetsMoveHarvestSpider(NavHarvesterMixin, CrawlSpider):
    """Unified nav+listing discovery pass, replacing the separate
    letsmove_harvest_nav/_list spiders and merge_harvest.py's reconciliation
    step for this site - same pattern as obama_whitehouse_harvest.py (see
    that spider's own docstring for the full rationale). One CrawlSpider:
    ordinary nav link-following flags a listing (is_listing=True) and never
    follows into its .view container; a still-curated LISTING_SEEDS list
    (just /blog/ for this site - the only known listing section) gets its
    pagination walked inline instead of merely flagged.

    Much smaller/lower-risk than the Obama WH version: one listing section
    (~98 pages, ~1,458 items, confirmed by a live walk 2026-07-26), not 255
    seeds across multiple shared-catalog-risk templates - no
    video/photogallery-style duplicate-catalog concern here.
    """

    name = "letsmove_harvest"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'letsmove.obamawhitehouse'
    EXCLUSIONS_FILE_SUFFIX = 'harvest-exclusions'

    # .view wraps both the blog listing's item rows and its <ul class="pager">
    # block (confirmed nested together on the live site, single .view
    # occurrence on the page - no related-content false-positive risk
    # observed). .pager is the signal a real pager is present (Drupal only
    # renders this block for a genuinely multi-page view), distinguishing a
    # real listing from any content page that might embed a single-item
    # .view widget with no pagination.
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['letsmove.obamawhitehouse.archives.gov'],
        deny_extensions=(),
    )
    LISTING_PAGER_SELECTOR = '.pager'

    # DEPTH_LIMIT raised from the old nav spider's 4 to comfortably clear
    # the /blog/ listing's full pagination chain (98 pages, confirmed via a
    # live walk 2026-07-26 - this site's pager URLs are opaque hashed
    # tokens, not sequential page numbers, so this had to be walked rather
    # than inferred from the markup). Same DepthMiddleware-shares-one-counter
    # reasoning as obama_whitehouse_harvest.py: without raising this,
    # _walk_listing_pagination's own pager-following would get silently cut
    # off well short of the listing's true end. Old nav's DEPTH_LIMIT=4 was
    # narrow enough that 5 extra start_urls had to be added by hand for
    # pages "confirmed beyond depth 4" - kept below for now (harmless, and
    # not the focus of this reunification), but raising the ceiling this
    # much may make some of them redundant; not re-verified this session.
    custom_settings = {
        'DEPTH_LIMIT': 200,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEED_EXPORT_FIELDS': ['url', 'is_listing', 'depth'],
    }

    # The one known listing section on this site. Unlike Obama WH's 255
    # human-curated entries, this list has never needed growing - the old
    # split-harvester model only ever seeded /blog/ here too.
    LISTING_SEEDS = [
        "https://letsmove.obamawhitehouse.archives.gov/blog/",
    ]

    start_urls = [
        "https://letsmove.obamawhitehouse.archives.gov/",
        # Pages confirmed beyond depth 4 from the homepage under the old,
        # narrower DEPTH_LIMIT - ported unchanged, not re-verified against
        # the new higher ceiling.
        "https://letsmove.obamawhitehouse.archives.gov/Tweetup",
        "https://letsmove.obamawhitehouse.archives.gov/get-email-updates",
        "https://letsmove.obamawhitehouse.archives.gov/meetup",
        "https://letsmove.obamawhitehouse.archives.gov/promote-affordable-accessible-food",
        "https://letsmove.obamawhitehouse.archives.gov/share-your-story-lets-move-olympic-fun-day",
    ] + LISTING_SEEDS

    rules = (
        Rule(
            LinkExtractor(deny_extensions=()),
            callback='parse_nav',
            follow=False,
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listing_seed_urls = set(self.LISTING_SEEDS)

    def parse_start_url(self, response):
        """CrawlSpider routes every start_urls response here instead of the
        Rule's own callback - same dispatch as obama_whitehouse_harvest.py."""
        if response.url in self._listing_seed_urls:
            yield {
                'url': response.url,
                'is_listing': True,
                'depth': response.request.meta.get('depth', 0) if response.request else 0,
            }
            yield from self._walk_listing_pagination(response)
        else:
            yield from self.parse_nav(response)

    def _walk_listing_pagination(self, response):
        """Extract this listing page's items and follow its own pager,
        recursing through subsequent pages via this same callback - ported
        from the old letsmove_harvest_list.py's parse(). Does NOT flag
        subsequent pagination pages as their own is_listing record - only
        the seed's entry point gets one, via parse_start_url."""
        links = response.css('.views-row .views-field-title a::attr(href)').getall()
        if not links:
            return

        rules = self._get_exclusion_rules()
        for href in links:
            url = response.urljoin(href)
            reason = exclusion_rules.match_exclude(url, rules)
            if reason is not None:
                self._log_exclusion(url, reason)
                continue
            yield {'url': url}

        self._census_links(response)

        next_page = response.css('.pager-next a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self._walk_listing_pagination)
