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
    # table-based photo/video gallery view both render inside a .view
    # div). A populated match distinguishes an actual listing from a content
    # page that merely embeds a single-item view (confirmed: known listing
    # pages carry a .pager inside their .view, the known Weekly Address
    # single-item-view false positive does not).
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['obamawhitehouse.archives.gov'],
    )

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
            # No nav_deny patterns for this domain today, but wired through
            # the same mechanism as every other nav harvester for consistency
            # (see NavHarvesterMixin._apply_nav_deny).
            process_links='_apply_nav_deny',
        ),
    )
