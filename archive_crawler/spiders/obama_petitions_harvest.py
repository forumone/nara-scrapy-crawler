import scrapy


class ObamaPetitionsHarvestSpider(scrapy.Spider):
    name = "obama_petitions_harvest"
    allowed_domains = ["petitions.obamawhitehouse.archives.gov"]
    start_urls = [
        "https://petitions.obamawhitehouse.archives.gov/",
        "https://petitions.obamawhitehouse.archives.gov/about",
        "https://petitions.obamawhitehouse.archives.gov/how-petitions-work",
    ]

    def parse(self, response):
        if response.url.rstrip('/').endswith('archives.gov'):
            for href in response.css('article h3 a::attr(href)').getall():
                yield {'url': response.urljoin(href)}
        else:
            yield {'url': response.url}
