import csv
import os

import scrapy
from scrapy.utils.gz import gunzip
from scrapy.utils.sitemap import Sitemap

from archive_crawler import exclusion_rules


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

    Pass -a source_site=<name> to load that domain's extension allowlist
    from archive_crawler/exclusion_rules/<name>.yml (e.g. to admit PDFs on a
    site with a document sitemap). Without it, the shared default extension
    allowlist is used (html/htm/php/asp/aspx/shtml/cfm/cgi). -a rules_file
    and -a rules_mode=append|replace overlay a per-run override on top of
    source_site's committed file, same as every other spider.
    """

    name = "sitemap_harvest"

    # Some sites' sitemap URLs themselves 301 (e.g. a WordPress/Yoast site
    # serving /sitemap.xml -> /sitemap_index.xml); under the project-wide
    # REDIRECT_ENABLED=False default that redirect is silently dropped
    # instead of followed, yielding zero items instead of an error. Safe to
    # re-enable here since this spider only ever fetches sitemap/index XML,
    # never a content page - no redirect-detection signal is being traded
    # away.
    custom_settings = {'REDIRECT_ENABLED': True}

    def __init__(self, sitemap_url=None, dropped_file=None, source_site=None,
                 rules_file=None, rules_mode='append', *args, **kwargs):
        if not sitemap_url:
            raise ValueError(
                "sitemap_url is required: "
                "-a sitemap_url=https://example.com/sitemap.xml"
            )
        self._start_url = sitemap_url
        self._seen = set()
        self._dropped_file = dropped_file
        self._dropped = []
        self._exclusion_rules = (
            exclusion_rules.load_rules(source_site, rules_file, rules_mode)
            if source_site else
            exclusion_rules.ExclusionRules()
        )
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
                if not exclusion_rules.is_web_url(url, self._exclusion_rules):
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
