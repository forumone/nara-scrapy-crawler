import scrapy


class ObamaWhiteHouseHarvestSpider(scrapy.Spider):
    name = "obama_whitehouse_harvest"
    allowed_domains = ["obamawhitehouse.archives.gov"]
    start_urls = [
        "https://obamawhitehouse.archives.gov/briefing-room/speeches-and-remarks",
        "https://obamawhitehouse.archives.gov/briefing-room/press-briefings",
        "https://obamawhitehouse.archives.gov/briefing-room/statements-and-releases",
        "https://obamawhitehouse.archives.gov/briefing-room/presidential-actions",
        "https://obamawhitehouse.archives.gov/briefing-room/weekly-address",
        "https://obamawhitehouse.archives.gov/blog",
    ]

    def parse(self, response):
        if not response.css('.views-row'):
            return

        for href in response.css('.views-row h2 a::attr(href), .views-row h3 a::attr(href)').getall():
            yield {'url': response.urljoin(href)}

        next_page = response.css('.pager-next a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
