import scrapy


class ObamaPetitionsHarvestSpider(scrapy.Spider):
    name = "obama_petitions_harvest"
    allowed_domains = ["petitions.obamawhitehouse.archives.gov"]

    # See open_obama_whitehouse_harvest.py's identical override - guards
    # against the same silent-truncation-on-301 failure mode under the
    # project-wide REDIRECT_ENABLED=False default, should this site's start
    # pages ever redirect the way its sibling sites' pagers do.
    custom_settings = {'REDIRECT_ENABLED': True}
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
