import re

from scrapy.linkextractors import LinkExtractor
from scrapy.selector import Selector
from scrapy.spiders import CrawlSpider, Rule
from w3lib.html import remove_tags_with_content

from archive_crawler.items import ArchiveItem


def _teaser(text, min_offset=60, max_len=200, truncate_after=False):
    """Return a teaser string: the first sentence of text (skipping the first
    min_offset characters to avoid splitting on abbreviations), capped near max_len
    at a word boundary.

    truncate_after=False (default): cut back to the last space before max_len, so the
                                   teaser is always strictly shorter than max_len.
    truncate_after=True:            extend past max_len to the next space, so the
                                   teaser may slightly exceed max_len.
    """
    if not text:
        return ''
    m = re.search(r'[.!?](?=\s+[A-Z])', text[min_offset:])
    result = text[:min_offset + m.end()] if m else text
    if len(result) <= max_len:
        return result
    if truncate_after:
        next_space = result.find(' ', max_len)
        return result[:next_space] if next_space != -1 else result
    truncated = result[:max_len]
    last_space = truncated.rfind(' ')
    return truncated[:last_space] if last_space > 0 else truncated


class LetsMoveSpider(CrawlSpider):
    name = "letsmove"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]
    start_urls = ["https://letsmove.obamawhitehouse.archives.gov/"]

    SOURCE_SITE = 'letsmove.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    rules = (
        Rule(
            LinkExtractor(
                deny=(
                    r'/sites/',   # static assets (CSS, JS, images)
                    r'/user/',    # Drupal user pages
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

        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = _teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def _extract_text(self, response, selector):
        match = response.css(selector).get()
        if not match:
            return ''
        try:
            cleaned = remove_tags_with_content(match, which_ones=('script', 'style'))
        except TypeError:
            cleaned = ''
        text = Selector(text=cleaned).xpath('string(.)').get(default='')
        return re.sub(r'\s+', ' ', text).strip()
