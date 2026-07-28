from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class LetsMoveHarvestSpider(NavHarvesterMixin, CrawlSpider):
    """Unified nav+listing discovery pass for
    letsmove.obamawhitehouse.archives.gov - same pattern as
    obama_whitehouse_harvest.py (see that spider's docstring, and
    ARCHITECTURE.md for the shared fingerprint mechanism). One CrawlSpider:
    ordinary nav link-following flags a listing (is_listing=True),
    fingerprints its item-URL set, and auto-walks its pagination the first
    time that fingerprint is seen - no curated seed list.

    Much smaller/lower-risk than the Obama WH site: one main listing section
    (/blog/), no video/photogallery-style shared-catalog concern. Individual
    blog posts also embed a "recent posts" widget sharing the same view id
    and pager-token scheme as /blog/'s own listing - if its item set is
    identical across posts, the fingerprint mechanism collapses it the same
    way as any other shared catalog; if it varies per post, each gets walked
    once, which is harmless at this site's scale either way.
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

    # DEPTH_LIMIT raised to comfortably clear the /blog/ listing's full
    # pagination chain (this site's pager URLs are opaque hashed tokens, not
    # sequential page numbers, so the chain length has to be walked rather
    # than inferred from the markup). Same DepthMiddleware-shares-one-counter
    # reasoning as obama_whitehouse_harvest.py: without raising this,
    # _walk_listing_pagination's own pager-following would get silently cut
    # off well short of the listing's true end.
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
