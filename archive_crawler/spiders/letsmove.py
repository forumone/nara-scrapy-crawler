from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class LetsMoveSpider(ArchiveSpiderMixin, CrawlSpider):
    name = "letsmove"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]
    start_urls = ["https://letsmove.obamawhitehouse.archives.gov/"]

    SOURCE_SITE = 'letsmove.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    rules = (
        Rule(
            LinkExtractor(
                deny=(
                    r'/sites/',     # static assets (CSS, JS, images)
                    r'/user/',      # Drupal user pages
                    r'/node/\d',    # raw Drupal node paths (redirect noise)
                    r'/print/',     # Drupal print views (duplicate content)
                    r'/category/',  # listing views (low-value, pagination-heavy)
                ),
            ),
            callback='parse_item',
            follow=True,
        ),
    )

    def parse_item(self, response):
        # Listing and pagination pages use div.view rather than div.node — their
        # body extraction returns empty, so they're naturally skipped here while
        # CrawlSpider still follows links from them (follow=True).
        body = self._extract_text(response, '#maincontent .node .content')
        if not body:
            return

        title = (response.css('#maincontent h1').xpath('string(.)').get(default='')).strip()
        if not title:
            return

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
