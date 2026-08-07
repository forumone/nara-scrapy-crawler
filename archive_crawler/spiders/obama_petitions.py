from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import PetitionsSpiderMixin
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin


class ObamaPetitionsSpider(PetitionsSpiderMixin, NavHarvesterMixin, CrawlSpider):
    """Nav-harvest + content-scrape spider for
    petitions.obamawhitehouse.archives.gov, which has no sitemap. One
    CrawlSpider does both ordinary nav link-following and content extraction
    (_scrape_item, PetitionsSpiderMixin's role) on the same fetched response
    - no separate harvest pass.

    No listing-fingerprint dedup: the site's petition list is a single flat
    page with no pager, so there's no paginated listing to fingerprint or
    walk in the first place.
    """

    name = "obama_petitions"
    allowed_domains = ["petitions.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'petitions.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    # DEPTH_LIMIT raised past the mixin's usual 2 - a full unlimited-depth
    # crawl of this site reaches depth 3 at most (confirmed via the prior
    # generic_crawl_harvest-based harvest), so this leaves a comfortable
    # margin.
    #
    # FEEDS produces both harvest and content CSVs from this one run, via
    # two named feeds each item_classes-filtered to the matching schema.
    custom_settings = {
        'DEPTH_LIMIT': 20,
        'REDIRECT_ENABLED': True,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEEDS': {
            'data/petitions.obamawhitehouse/petitions.obamawhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/petitions.obamawhitehouse/petitions.obamawhitehouse.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [ArchiveItem],
                'fields': [
                    'url', 'title', 'teaser_text', 'full_text',
                    'source_site', 'source_type', 'warnings',
                ],
            },
        },
    }

    start_urls = ['https://petitions.obamawhitehouse.archives.gov/']

    rules = (
        Rule(
            # allow= anchors to the exact hostname; allow_domains alone would
            # also match a subdomain sharing this suffix.
            LinkExtractor(
                allow=r'//petitions\.obamawhitehouse\.archives\.gov/',
                allow_domains=['petitions.obamawhitehouse.archives.gov'],
                deny_extensions=(),
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav
        ),
    )
