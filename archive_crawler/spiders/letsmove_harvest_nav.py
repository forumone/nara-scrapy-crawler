from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.spiders.base import NavHarvesterMixin


class LetsMoveHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
    name = "letsmove_harvest_nav"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]
    start_urls = ["https://letsmove.obamawhitehouse.archives.gov/"]

    custom_settings = {
        'DEPTH_LIMIT': 4,
    }

    rules = (
        Rule(
            LinkExtractor(
                deny=(
                    r'/sites/',
                    r'/user/',
                    r'/node/\d',
                    r'/print/',
                    r'/category/',
                ),
            ),
            callback='parse_nav',
            follow=False,
        ),
    )
