"""
Generic harvest spider — phase 1 of the two-phase crawl workflow.

Crawls a site from a single entry-point URL, follows all internal links,
and writes a URL-per-row CSV. That CSV is the input to generic_crawl (phase 2).

Use this spider for simple sites with no paginated listing sections, where all
content is reachable by following navigation links. See HARVESTING.md for
guidance on when to use this vs. the split nav+list harvester pattern.

Usage
-----
Basic crawl of an entire domain:

    scrapy crawl generic_crawl_harvest \
        -a url=https://example.archives.gov/ \
        -o data/example_harvest.csv

Excluding paths that generate noise (comma-separated regex fragments):

    scrapy crawl generic_crawl_harvest \
        -a url=https://example.archives.gov/ \
        -a urls_to_skip='/print/,/user/,/node/\\d' \
        -o data/example_harvest.csv

Arguments
---------
url          Required. The root URL to start crawling. The spider confines
             itself to the domain extracted from this URL.
urls_to_skip Optional. Comma-separated list of regex fragments passed as
             deny patterns to the LinkExtractor. Useful for excluding
             Drupal print views, user pages, raw node paths, etc.

Customising for a new site
--------------------------
If the generic deny rules aren't sufficient, subclass this spider and override
rules with a site-specific LinkExtractor. The harvest output format (a single
'url' column) must stay the same so generic_crawl can consume it unchanged.
"""
from urllib.parse import urlparse

from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule


class GenericCrawlHarvestSpider(CrawlSpider):
    name = "generic_crawl_harvest"

    def __init__(self, url=None, urls_to_skip=None, *args, **kwargs):
        if not url:
            raise ValueError("No 'url' argument provided.")

        self.start_urls = [url]
        self.allowed_domains = [urlparse(url).netloc]

        deny_list = []
        if urls_to_skip:
            deny_list = [s.strip() for s in urls_to_skip.split(',') if s.strip()]

        self.rules = (
            Rule(
                LinkExtractor(deny=(r'\?page=', r'/page/', *deny_list), unique=True),
                callback='parse_url',
                follow=True,
            ),
        )

        super().__init__(*args, **kwargs)

    def parse_url(self, response):
        yield {'url': response.url}
