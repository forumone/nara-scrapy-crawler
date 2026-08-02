import scrapy


class TrumpPetitionsHarvestSpider(scrapy.Spider):
    name = "trump_petitions_harvest"
    allowed_domains = ["petitions.trumpwhitehouse.archives.gov"]

    # See open_obama_whitehouse_harvest.py's identical override - this site's
    # pager links also 301 to a canonicalized URL, silently truncating
    # pagination under the project-wide REDIRECT_ENABLED=False default.
    #
    # Output path is automatic, derived from this spider's own site - pass
    # -O <path> on the CLI to override.
    custom_settings = {
        'REDIRECT_ENABLED': True,
        'FEEDS': {
            'data/petitions.trumpwhitehouse/petitions.trumpwhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'fields': ['url'],
            },
        },
    }
    start_urls = [
        "https://petitions.trumpwhitehouse.archives.gov/",
        "https://petitions.trumpwhitehouse.archives.gov/about",
        "https://petitions.trumpwhitehouse.archives.gov/developers",
    ]

    def parse(self, response):
        if '?page=' in response.url or response.url.rstrip('/').endswith('archives.gov'):
            yield from self._parse_listing(response)
        else:
            yield from self._parse_static(response)

    def _parse_listing(self, response):
        for href in response.css('article.node-petition h3 a::attr(href)').getall():
            yield {'url': response.urljoin(href)}

        next_page = response.css(
            '.views-pager-history-next .page-load-next a::attr(href)'
        ).get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def _parse_static(self, response):
        yield {'url': response.url}
        for href in response.css('#sidebar-top .menu a::attr(href)').getall():
            yield response.follow(href, callback=self._parse_static)
