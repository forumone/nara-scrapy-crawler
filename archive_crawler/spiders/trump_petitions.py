import re

import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class TrumpPetitionsSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "trump_petitions"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]
    start_urls = [
        "https://petitions.trumpwhitehouse.archives.gov/",
        "https://petitions.trumpwhitehouse.archives.gov/about",
        "https://petitions.trumpwhitehouse.archives.gov/developers",
    ]

    SOURCE_SITE = 'petitions.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen = set()

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
        if response.url in self._seen:
            return
        self._seen.add(response.url)
        item = ArchiveItem()
        item['url'] = response.url
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            return
        item['title'] = title

        date = re.sub(r'\s+', ' ', response.css('h4.petition-attribution::text').get(default='')).strip()
        body = self._extract_text(response, '.field-name-body .field-items .field-item')

        # Append date attribution to full_text; teaser is sourced from body only
        full_text = f"{body} {date}".strip() if (date and any(c.isdigit() for c in date)) else body
        item['full_text'] = full_text
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def generic_page_parse(self, response):
        if response.url in self._seen:
            return
        self._seen.add(response.url)
        item = ArchiveItem()
        item['url'] = response.url
        title = response.css('h1.title::text').get(default='').strip()
        if not title:
            title = response.css('h1::text').get(default='').strip()
        if not title:
            return
        item['title'] = title

        body = self._extract_text(response, '.field-name-body .field-items .field-item')
        if not body:
            body = self._extract_text(response, '#content-main')

        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

        for href in response.css('#sidebar-top .menu a::attr(href)').getall():
            yield response.follow(href, callback=self.parse)
