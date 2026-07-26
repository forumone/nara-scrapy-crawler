from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class LetsMoveHarvestSpider(NavHarvesterMixin, CrawlSpider):
    """Unified nav+listing discovery pass, replacing the separate
    letsmove_harvest_nav/_list spiders and merge_harvest.py's reconciliation
    step for this site - same pattern as obama_whitehouse_harvest.py (see
    that spider's own docstring for the full rationale). One CrawlSpider:
    ordinary nav link-following flags a listing (is_listing=True), fingerprints
    its item-URL set, and auto-walks its pagination the first time that
    fingerprint is seen (NavHarvesterMixin's fingerprint mechanism - no
    curated seed list).

    Much smaller/lower-risk than the Obama WH version: one main listing
    section (~98 pages, ~1,458 items, confirmed by a live walk 2026-07-26),
    not 255 seeds across multiple shared-catalog-risk templates - no
    video/photogallery-style duplicate-catalog concern here. Individual blog
    posts also embed a "recent posts" widget sharing the same view id
    (most_recent) and pager-token scheme as /blog/'s own listing - if its
    item set is identical across posts, the fingerprint mechanism collapses
    it the same way as any other shared catalog; if it varies per post, each
    gets walked once, which is harmless at this site's scale either way.
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
    ]

    rules = (
        Rule(
            LinkExtractor(deny_extensions=()),
            callback='parse_nav',
            follow=False,
        ),
    )

    def _listing_pagination_items(self, response):
        return response.css('.views-row .views-field-title a::attr(href)').getall()

    def _listing_pagination_next_url(self, response):
        return response.css('.pager-next a::attr(href)').get()
