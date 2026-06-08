from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class ObamaWhiteHouseSpider(ArchiveSpiderMixin, CrawlSpider):
    name = "obama_whitehouse"
    allowed_domains = ["obamawhitehouse.archives.gov"]
    start_urls = ["https://obamawhitehouse.archives.gov/"]

    SOURCE_SITE = 'obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    rules = (
        Rule(
            LinkExtractor(
                deny=(
                    r'/sites/',    # static assets (CSS, JS, images)
                    r'/user/',     # Drupal user pages
                    r'/node/\d',   # raw Drupal node paths (redirect noise)
                    r'/print/',    # Drupal print views (duplicate content)
                ),
            ),
            callback='parse_item',
            follow=True,
        ),
    )

    def parse_item(self, response):
        # Listing and pagination pages have no .field-items and are skipped naturally.
        body = self._extract_text(response, '.field-items .field-item')
        if not body:
            return

        title = response.css('h1').xpath('string(.)').get(default='').strip()
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
