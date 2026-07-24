import csv
import os

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

    Pass -a dropped_file=data/example/example_harvest-dropped.csv to also
    record every non-web-extension URL dropped during the harvest (PDFs,
    images, etc.) — otherwise those drops are only summarized in the log.
    """

    name = "sitemap_harvest"

    def __init__(self, sitemap_url=None, dropped_file=None, *args, **kwargs):
        if not sitemap_url:
            raise ValueError(
                "sitemap_url is required: "
                "-a sitemap_url=https://example.com/sitemap.xml"
            )
        self._start_url = sitemap_url
        self._seen = set()
        self._dropped_file = dropped_file
        self._dropped = []
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
                if key in self._seen:
                    continue
                if not _is_web_url(url):
                    self._dropped.append({'url': url, 'reason': 'non_web_extension'})
                    continue
                self._seen.add(key)
                yield {'url': url}

    def closed(self, reason):
        if not self._dropped:
            return
        self.logger.info(
            "Dropped %d non-web-extension URL(s) during sitemap harvest",
            len(self._dropped),
        )
        if not self._dropped_file:
            return
        out_dir = os.path.dirname(self._dropped_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(self._dropped_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'reason'])
            writer.writeheader()
            writer.writerows(self._dropped)
