import re

import scrapy
from scrapy.selector import Selector
from w3lib.html import remove_tags_with_content

from archive_crawler.items import ArchiveItem


def _teaser(text, min_offset=60, max_len=200, truncate_after=True):
    """Return a teaser string: the first sentence of text (skipping the first
    min_offset characters to avoid splitting on abbreviations), capped near max_len
    at a word boundary.

    truncate_after=True  (default): extend past max_len to the next space, so the
                                    teaser may slightly exceed max_len.
    truncate_after=False:           cut back to the last space before max_len, so the
                                    teaser is always strictly shorter than max_len.
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


class ObamaPetitionsSpider(scrapy.Spider):
    name = "obama_petitions"
    allowed_domains = ["petitions.obamawhitehouse.archives.gov"]
    start_urls = [
        "https://petitions.obamawhitehouse.archives.gov/",
        "https://petitions.obamawhitehouse.archives.gov/about",
        "https://petitions.obamawhitehouse.archives.gov/how-petitions-work",
    ]

    SOURCE_SITE = 'petitions.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def parse(self, response):
        if '/petition/' in response.url:
            yield from self.petition_page_parse(response)
        elif response.url.rstrip('/').endswith('archives.gov'):
            yield from self.listing_page_parse(response)
        else:
            yield from self.generic_page_parse(response)

    def listing_page_parse(self, response):
        for href in response.css('article h3 a::attr(href)').getall():
            yield response.follow(href, callback=self.petition_page_parse)

    def petition_page_parse(self, response):
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.css('h1.title::text').get(default='').strip()

        body = self._extract_text(response, '.field-name-body .field-items .field-item')

        item['full_text'] = body
        item['teaser_text'] = _teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def generic_page_parse(self, response):
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.css('h1.title::text').get(default='').strip()

        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            body = self._extract_text(response, '#content-main')

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
