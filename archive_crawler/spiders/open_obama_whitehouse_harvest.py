import scrapy


class OpenObamaWhiteHouseHarvestSpider(scrapy.Spider):
    name = "open_obama_whitehouse_harvest"
    allowed_domains = ["open.obamawhitehouse.archives.gov"]
    start_urls = [
        "https://open.obamawhitehouse.archives.gov",
        "https://open.obamawhitehouse.archives.gov/budget",
        "https://open.obamawhitehouse.archives.gov/search",
    ]

    def parse(self, response):
        if 'search' in response.url:
            yield from self._parse_search(response)
        elif 'dataset' in response.url:
            yield from self._parse_dataset(response)
        else:
            yield {'url': response.url}

    def _parse_search(self, response):
        for href in response.css('div.views-row h2 a::attr(href)').getall():
            yield response.follow(href, callback=self._parse_dataset)

        next_page = response.css('li.pager-next a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self._parse_search)

    def _parse_dataset(self, response):
        yield {'url': response.url}
        child_resource = response.css('span.links a::attr(href)').get()
        if child_resource:
            yield response.follow(child_resource, callback=self._parse_dataset)
