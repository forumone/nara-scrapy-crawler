from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor
from urllib.parse import urlparse
from archive_crawler.items import ArchiveItem
import re

class GenericCrawlSpider(CrawlSpider):
    name = "generic_crawl"

    def __init__(self, url=None, urls_to_skip=None, site_id='archive', *args, **kwargs):
        # 1. Validation
        if not url:
            raise ValueError("No 'url' argument provided.")

        # 2. Setup Start URLs and Allowed Domains
        self.start_urls = [url]

        # Extract domain (e.g., "example.com") from the URL to constrain the crawl
        domain = urlparse(url).netloc
        self.allowed_domains = [domain]
        self.site_id = site_id

        # 3. Process the Skip List (Deny List)
        deny_list = []
        if urls_to_skip:
            # Split comma-separated string into a list
            deny_list = [s.strip() for s in urls_to_skip.split(',') if s.strip()]

        # 4. Construct Rules Dynamically
        # We build the rules list here before calling super().__init__
        self.rules = (
            Rule(
                LinkExtractor(
                    # Allow anything on the same domain...
                    allow=(),
                    # ...Except things matching our skip list
                    deny=deny_list,
                    # unique=True ensures we don't crawl the same page twice
                    unique=True
                ),
                callback='parse_item',  # Call this method when a page is found
                follow=True  # Keep following links on that page
            ),
        )

        # 5. Initialize the Parent Class (which compiles the rules)
        super(GenericCrawlSpider, self).__init__(*args, **kwargs)

    def parse_item(self, response):
        item = ArchiveItem()

        # 1. Get URL
        item['url'] = response.url

        # 2. Extract Title (Scrapy Native)
        # .get(default='') prevents a crash if the tag is missing
        item['title'] = response.xpath("//h1[@class='maincontent_title']/text()").get(default='').strip()

        # 3. Extract Body Content
        # usage of xpath('string(.)') gets text from the div AND its children (like <b>, <span>, etc)
        # This mimics lxml's .text_content()
        raw_body = response.xpath("//div[@id='maincontent']/*/div[@class='content']").xpath('string(.)').get(default='')

        # Clean whitespace
        clean_body_content = re.sub(r'\s+', ' ', raw_body).strip()
        item['full_text'] = clean_body_content

        # 4. Teaser
        if clean_body_content:
            teaser_text = clean_body_content.split('.', 1)
            item['teaser_text'] = teaser_text[0] + '.'
        else:
            item['teaser_text'] = ''

        item['source_site'] = 'obamawhitehouse'

        yield item