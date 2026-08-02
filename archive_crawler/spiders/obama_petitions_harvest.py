import scrapy


class ObamaPetitionsHarvestSpider(scrapy.Spider):
    name = "obama_petitions_harvest"
    allowed_domains = ["petitions.obamawhitehouse.archives.gov"]

    # See open_obama_whitehouse_harvest.py's identical override - guards
    # against the same silent-truncation-on-301 failure mode under the
    # project-wide REDIRECT_ENABLED=False default, should this site's start
    # pages ever redirect the way its sibling sites' pagers do.
    #
    # Output path is automatic, derived from this spider's own site - pass
    # -O <path> on the CLI to override.
    custom_settings = {
        'REDIRECT_ENABLED': True,
        'FEEDS': {
            'data/petitions.obamawhitehouse/petitions.obamawhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'fields': ['url'],
            },
        },
    }
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
