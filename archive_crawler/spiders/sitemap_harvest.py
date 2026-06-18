import scrapy
from scrapy.utils.gz import gunzip
from scrapy.utils.sitemap import Sitemap

from archive_crawler.spiders.base import _is_web_url


class SitemapHarvestSpider(scrapy.Spider):
    """Generic sitemap URL harvester.

    Fetches a sitemap (or sitemap index), recurses into sub-sitemaps,
    deduplicates URLs (case-insensitive), drops non-web assets, and yields
    one {'url': url} item per discoverable content page — without fetching
    any of those pages.

    Usage:
        scrapy crawl sitemap_harvest \\
            -a sitemap_url=https://example.archives.gov/sitemap.xml \\
            -O data/example_harvest-full.csv
    """

    name = "sitemap_harvest"

    def __init__(self, sitemap_url=None, *args, **kwargs):
        if not sitemap_url:
            raise ValueError(
                "sitemap_url is required: "
                "-a sitemap_url=https://example.com/sitemap.xml"
            )
        self._start_url = sitemap_url
        self._seen = set()
        super().__init__(*args, **kwargs)

    def start_requests(self):
        yield scrapy.Request(self._start_url, callback=self._parse_sitemap)

    def _parse_sitemap(self, response):
        body = response.body
        if body[:3] == b'\x1f\x8b\x08' or response.url.endswith('.gz'):
            body = gunzip(body)

        sitemap = Sitemap(body)

        if sitemap.type == 'sitemapindex':
            for entry in sitemap:
                loc = entry.get('loc', '')
                if loc:
                    yield scrapy.Request(loc, callback=self._parse_sitemap)
        else:
            for entry in sitemap:
                url = entry.get('loc', '')
                if not url:
                    continue
                key = url.lower()
                if key in self._seen or not _is_web_url(url):
                    continue
                self._seen.add(key)
                yield {'url': url}
