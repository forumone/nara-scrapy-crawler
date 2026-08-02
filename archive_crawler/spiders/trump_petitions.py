from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import PetitionsSpiderMixin
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin


class TrumpPetitionsSpider(PetitionsSpiderMixin, NavHarvesterMixin, CrawlSpider):
    """Nav-harvest + content-scrape spider for
    petitions.trumpwhitehouse.archives.gov, which has no sitemap. One
    CrawlSpider does both ordinary nav link-following and content extraction
    (_scrape_item, PetitionsSpiderMixin's role) on the same fetched response
    - no separate harvest pass.

    No listing-fingerprint dedup: this site's petition listing is paginated
    (?page=N via a Drupal Views pager), but at this site's scale (a few
    hundred pages) there's no evidence of the same listing being embedded
    on many individual permalinks - the shared-catalog-fan-out risk the
    fingerprint mechanism exists for.
    """

    name = "trump_petitions"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]

    SOURCE_SITE = 'petitions.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    # DEPTH_LIMIT raised past the mixin's usual 2 - a full unlimited-depth
    # crawl of this site reaches depth 11 at most (confirmed via the prior
    # generic_crawl_harvest-based harvest), so this leaves a comfortable
    # margin.
    #
    # REDIRECT_ENABLED=True overrides the project-wide default: this site's
    # pager 301s to a canonicalized URL, and without following redirects
    # that truncates pagination after page 1.
    #
    # FEEDS replaces the old two-spider invocation with two named feeds from
    # this one run, item_classes-filtered to the matching schema.
    custom_settings = {
        'DEPTH_LIMIT': 30,
        'REDIRECT_ENABLED': True,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEEDS': {
            'data/petitions.trumpwhitehouse/petitions.trumpwhitehouse_harvest-full.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/petitions.trumpwhitehouse/petitions.trumpwhitehouse.csv': {
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

    start_urls = ['https://petitions.trumpwhitehouse.archives.gov/']

    rules = (
        Rule(
            # allow= anchors to the exact hostname; allow_domains alone would
            # also match a subdomain sharing this suffix.
            LinkExtractor(
                allow=r'//petitions\.trumpwhitehouse\.archives\.gov/',
                allow_domains=['petitions.trumpwhitehouse.archives.gov'],
                deny_extensions=(),
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav
        ),
    )
