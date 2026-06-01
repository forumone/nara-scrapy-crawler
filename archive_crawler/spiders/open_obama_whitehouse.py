from pathlib import Path

import scrapy

class OpenSpider(scrapy.Spider):
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

    def parse(self, response):
        if 'search' in response.url:
            yield scrapy.Request(response.url, callback=self.search_page_parse)
        elif 'dataset' in response.url:
            yield scrapy.Request(response.url, callback=self.dataset_page_parse)
        else:
            yield scrapy.Request(response.url, callback=self.generic_parse)

    def generic_parse(self, response):
        yield {
            "url": response.url,
            "title": response.xpath("//title/text()").get(),
            "full_text": response.css("p::text").getall(),
        }

    def dataset_page_parse(self, response):
        child_resource = response.css("span.links a::attr(href)").get()
        if child_resource is not None:
            yield response.follow(child_resource, callback=self.dataset_page_parse)

        yield {
            "url": response.url,
            "title": response.xpath("normalize-space(//div[contains(@class, 'radix-layouts-content')]//h2[@class='pane-title']/text())").get(),
            "full_text": response.css("div.field-name-body div.field-items p::text").getall(),
        }

    def search_page_parse(self, response):
        for result in response.css("div.views-row"):
            result_link = result.css("h2 a::attr(href)").get()
            yield response.follow(result_link, callback=self.dataset_page_parse)

        next_page = response.css("li.pager-next a::attr(href)").get()
        if next_page is not None:
            yield response.follow(next_page, callback=self.search_page_parse)

