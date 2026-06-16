import scrapy

from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin


class OpenSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "open_obama_whitehouse"
    allowed_domains = ["open.obamawhitehouse.archives.gov"]
    start_urls = [
        "https://open.obamawhitehouse.archives.gov",
        "https://open.obamawhitehouse.archives.gov/budget",
        "https://open.obamawhitehouse.archives.gov/dataset/2017-budget-authority",
        "https://open.obamawhitehouse.archives.gov/dataset/2017-budget-receipts",
        "https://open.obamawhitehouse.archives.gov/dataset/2017-budget-outlays",
        "https://open.obamawhitehouse.archives.gov/dataset/white-house-nominations-appointments-new",
        "https://open.obamawhitehouse.archives.gov/dataset/white-house-visitor-records-requests",
        "https://open.obamawhitehouse.archives.gov/dataset/2015-report-congress-white-house-staff",
        "https://open.obamawhitehouse.archives.gov/dataset/2012-annual-report-congress-white-house-staff",
        "https://open.obamawhitehouse.archives.gov/dataset/2013-report-congress-white-house-staff",
        "https://open.obamawhitehouse.archives.gov/search"
    ]

    SOURCE_SITE = 'open.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'

    def parse(self, response):
        if 'search' in response.url:
            yield scrapy.Request(response.url, callback=self.search_page_parse)
        elif 'dataset' in response.url:
            yield scrapy.Request(response.url, callback=self.dataset_page_parse)
        else:
            yield scrapy.Request(response.url, callback=self.generic_parse)

    def generic_parse(self, response):
        body = self._extract_text(response, 'body')
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.xpath("//title/text()").get(default='').strip()
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def dataset_page_parse(self, response):
        child_resource = response.css("span.links a::attr(href)").get()
        if child_resource is not None:
            yield response.follow(child_resource, callback=self.dataset_page_parse)

        body = self._extract_text(response, "div.field-name-body div.field-items")
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = response.xpath("normalize-space(//div[contains(@class, 'radix-layouts-content')]//h2[@class='pane-title']/text())").get(default='').strip()
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item

    def search_page_parse(self, response):
        for result in response.css("div.views-row"):
            result_link = result.css("h2 a::attr(href)").get()
            yield response.follow(result_link, callback=self.dataset_page_parse)

        next_page = response.css("li.pager-next a::attr(href)").get()
        if next_page is not None:
            yield response.follow(next_page, callback=self.search_page_parse)
