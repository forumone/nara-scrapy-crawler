import re

import scrapy
from scrapy.selector import Selector
from w3lib.html import remove_tags_with_content

from archive_crawler.items import ArchiveItem


class TrumpPetitionsSpider(scrapy.Spider):
    name = "trump_petitions"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]
    start_urls = [
        "https://petitions.trumpwhitehouse.archives.gov/",
        "https://petitions.trumpwhitehouse.archives.gov/about",
        "https://petitions.trumpwhitehouse.archives.gov/developers",
    ]

    SOURCE_SITE = 'petitions.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def parse(self, response):
        if '/petition/' in response.url:
            yield from self.petition_page_parse(response)
        elif '?page=' in response.url or response.url.rstrip('/').endswith('archives.gov'):
            yield from self.listing_page_parse(response)
        else:
            yield from self.generic_page_parse(response)

    def listing_page_parse(self, response):
        for href in response.css('article.node-petition h3 a::attr(href)').getall():
            yield response.follow(href, callback=self.petition_page_parse)

        next_page = response.css(
            '.views-pager-history-next .page-load-next a::attr(href)'
        ).get()
        if next_page:
            yield response.follow(next_page, callback=self.listing_page_parse)

    def petition_page_parse(self, response):
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.css('h1.title::text').get(default='').strip()

        date = response.css('h4.petition-attribution::text').get(default='').strip()
        body = self._extract_text(response, '.field-name-body .field-items .field-item')

        full_text = f"{date} {body}".strip() if date else body
        item['full_text'] = full_text
        item['teaser_text'] = full_text.split('.', 1)[0] + '.' if full_text else ''
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
        item['teaser_text'] = body.split('.', 1)[0] + '.' if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

        for href in response.css('#sidebar-top .menu a::attr(href)').getall():
            yield response.follow(href, callback=self.parse)

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
