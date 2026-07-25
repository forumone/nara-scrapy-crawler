from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class ObamaWhiteHouseHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
    name = "obama_whitehouse_harvest_nav"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    # Matches the content spider's SOURCE_SITE - shares its
    # archive_crawler/exclusion_rules/<SOURCE_SITE>.yml file.
    SOURCE_SITE = 'www.obamawhitehouse'

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
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['obamawhitehouse.archives.gov'],
    )
    LISTING_PAGER_SELECTOR = '.pager-current'

    # Raised from the mixin's default of 2: a full run at DEPTH_LIMIT=10
    # left only 3 confirmed-real content pages permanently unreachable (out
    # of 171 unique depth-exceeded URLs, the other 168 were just longer
    # paths to things already found via a shorter route) - 12 gives another
    # small margin. Overrides custom_settings entirely rather than just
    # DEPTH_LIMIT, so CRAWLSPIDER_FOLLOW_LINKS: False must be repeated here
    # too (see the mixin's own custom_settings comment for why).
    custom_settings = {
        'DEPTH_LIMIT': 12,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
    }

    # A large curated start_urls list used to be necessary to get reasonable
    # coverage within the old DEPTH_LIMIT=2. At DEPTH_LIMIT=10, a single
    # entry point reaches virtually everything within budget on a full
    # (non-timed-out) run - additional seeds should only be added back if
    # such a run still logs genuine depth-exceeded ignores for a section,
    # not preemptively.
    start_urls = [
        'https://obamawhitehouse.archives.gov/',
    ]

    rules = (
        Rule(
            # allow= anchors to the exact hostname; allow_domains alone would
            # also match subdomains like letsmove.obamawhitehouse.archives.gov.
            LinkExtractor(
                allow=r'//obamawhitehouse\.archives\.gov/',
                allow_domains=['obamawhitehouse.archives.gov'],
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav, only from non-listing pages
        ),
    )
