import scrapy


class LetsMoveHarvestListSpider(scrapy.Spider):
    name = "letsmove_harvest_list"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]
    start_urls = ["https://letsmove.obamawhitehouse.archives.gov/blog/"]

    def parse(self, response):
        for href in response.css('.views-row .views-field-title a::attr(href)').getall():
            yield {'url': response.urljoin(href)}

        next_page = response.css('.pager-next a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
