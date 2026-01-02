from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor
from urllib.parse import urlparse
from archive_crawler.items import ArchiveItem
from scrapy.selector import Selector
from w3lib.html import remove_tags_with_content
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
        # There are several different title structures we are capturing with xpath "or" logic.
        title_xpath_query = "//h1[@class='maincontent_title'] | //*[@id='maincontent']/div/div[1]/h2 | //*[@id='maincontent']/h1"
        title = response.xpath(title_xpath_query).xpath('string(.)').get(default='missing_title').strip()
        item['title'] = title

        # 3. Extract Body Content
        # Some body fields have style and script tags. We don't want the contents of these elements. So we first load
        # the match, drop or remove the tags we don't want and then load it back into scrapy selector to finish the
        # the white space removal.
        body_xpath_query = "//div[@id='maincontent']/*/div[@class='content'] | //div[starts-with(@id, 'node-')]/div/p"
        match_body = response.xpath(body_xpath_query).get()
        # Remove the <style> and <script> tags inside this specific area
        # @todo: revisit this logic as it doesn't work for https://letsmove.obamawhitehouse.archives.gov/gardening-guide.
        try:
            body_without_style_and_script = remove_tags_with_content(match_body, which_ones=('script', 'style'))
        except TypeError:
            body_without_style_and_script = ''

        clean_selector = Selector(text=body_without_style_and_script)
        raw_body = clean_selector.xpath('string(.)').get(default='missing_body')
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