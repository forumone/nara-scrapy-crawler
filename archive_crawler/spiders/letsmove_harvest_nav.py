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

    custom_settings = {
        'DEPTH_LIMIT': 4,
    }

    rules = (
        Rule(
            LinkExtractor(),
            callback='parse_nav',
            follow=False,
            # deny patterns come from archive_crawler/exclusion_rules/
            # letsmove.obamawhitehouse.yml's nav_deny list, resolved at
            # _compile_rules() time (see NavHarvesterMixin._apply_nav_deny).
            process_links='_apply_nav_deny',
        ),
    )
