from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class LetsMoveHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
    name = "letsmove_harvest_nav"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]

    # Matches the content spider's SOURCE_SITE - shares its
    # archive_crawler/exclusion_rules/<SOURCE_SITE>.yml file.
    SOURCE_SITE = 'letsmove.obamawhitehouse'

    start_urls = [
        "https://letsmove.obamawhitehouse.archives.gov/",
        # Pages confirmed beyond depth 4 from the homepage
        "https://letsmove.obamawhitehouse.archives.gov/Tweetup",
        "https://letsmove.obamawhitehouse.archives.gov/get-email-updates",
        "https://letsmove.obamawhitehouse.archives.gov/meetup",
        "https://letsmove.obamawhitehouse.archives.gov/promote-affordable-accessible-food",
        "https://letsmove.obamawhitehouse.archives.gov/share-your-story-lets-move-olympic-fun-day",
    ]

    # Overrides NavHarvesterMixin.custom_settings entirely (Python class
    # attributes don't merge) - CRAWLSPIDER_FOLLOW_LINKS: False must be
    # repeated here, or CrawlSpider's own built-in link-following silently
    # re-enables for this spider specifically (see the mixin's own
    # custom_settings comment for why that matters).
    custom_settings = {
        'DEPTH_LIMIT': 4,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
    }

    rules = (
        Rule(
            LinkExtractor(),
            callback='parse_nav',
            follow=False,
        ),
    )
