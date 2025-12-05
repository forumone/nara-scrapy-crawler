import scrapy
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor
from urllib.parse import urlparse
from archive_crawler.items import ArchiveItem


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
        """
        This function is called for every page that matches the rules.
        """
        item = ArchiveItem()
        item['url'] = response.url
        item['source_site'] = self.site_id

        # Extract Title
        item['title'] = response.css('title::text').get(default='').strip()

        # Extract Content (Basic Text Extraction)
        # You might want to filter out navigation/footer text here in the future
        paragraphs = response.css('body p::text').getall()
        clean_text = " ".join([p.strip() for p in paragraphs if p.strip()])
        item['content'] = clean_text

        # Extract Date
        item['published_date'] = response.xpath('//meta[@name="date"]/@content').get()

        yield item