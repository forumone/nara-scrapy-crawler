import csv
import os

import scrapy
from scrapy.utils.gz import gunzip
from scrapy.utils.sitemap import Sitemap

from archive_crawler import exclusion_rules


class SitemapHarvestSpider(scrapy.Spider):
    """Generic sitemap URL harvester.

    Fetches a sitemap (or sitemap index), recurses into sub-sitemaps,
    deduplicates URLs (case-insensitive), drops non-web assets, and writes
    one row per discoverable content page - without fetching any of those
    pages.

    Usage:
        scrapy crawl sitemap_harvest \\
            -a sitemap_url=https://example.archives.gov/sitemap.xml \\
            -a source_site=example

    Output is automatic, derived from source_site: harvest_file defaults to
    data/<source_site>/<source_site>_harvest-full.csv, and dropped_file
    (non-web-extension URLs, only written if at least one was dropped)
    defaults to data/<source_site>/<source_site>_harvest-dropped.csv. Pass
    -a harvest_file=<path> and/or -a dropped_file=<path> to override either
    default explicitly. If source_site isn't given, harvest_file must be
    passed explicitly (there's nothing to derive a path from), and dropped
    URLs are only summarized in the log, not written to a file, unless
    dropped_file is also passed explicitly.

    Unlike every other spider in this project, -O/-o do NOT control this
    spider's output. It writes plain CSVs directly in closed() - the same
    mechanism the exclusions-file logging already uses - rather than via
    Scrapy's FEEDS/FeedExporter, since source_site (and therefore the
    default path) isn't known until the spider is instantiated with its
    runtime -a arguments, which is after Scrapy would already have read
    custom_settings from the class.

    Pass -a source_site=<name> to load that domain's extension allowlist
    from archive_crawler/exclusion_rules/<name>.yml (e.g. to admit PDFs on a
    site with a document sitemap). Without it, the shared default extension
    allowlist is used (html/htm/php/asp/aspx/shtml/cfm/cgi). -a rules_file
    and -a rules_mode=append|replace overlay a per-run override on top of
    source_site's committed file, same as every other spider.

    Only the extension allowlist is applied here - the rest of a site's
    committed rules_file (url-pattern excludes, etc.) is not, since those
    are evaluated per-content-page at the content spider's own
    start_requests, not during harvest. Don't be surprised if the final
    item count comes in well under the sitemap's raw URL total on a site
    with a lot of non-HTML assets listed in it (e.g. georgewbush-whitehouse:
    ~229k raw sitemap entries, ~222k after this filter, ~6.5k dropped as
    PDFs/images/etc.) - that gap is expected, not a sign the harvest ran
    short.
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

    def __init__(self, sitemap_url=None, harvest_file=None, dropped_file=None,
                 source_site=None, rules_file=None, rules_mode='append',
                 *args, **kwargs):
        if not sitemap_url:
            raise ValueError(
                "sitemap_url is required: "
                "-a sitemap_url=https://example.com/sitemap.xml"
            )
        self._start_url = sitemap_url
        self._seen = set()
        self._harvested = []
        self._harvest_file = harvest_file or (
            os.path.join('data', source_site, f'{source_site}_harvest-full.csv')
            if source_site else None
        )
        if not self._harvest_file:
            raise ValueError(
                "harvest_file is required when source_site is not given: "
                "-a harvest_file=data/example/example_harvest-full.csv "
                "(or pass -a source_site=<name> to derive it automatically)"
            )
        self._dropped_file = dropped_file or (
            os.path.join('data', source_site, f'{source_site}_harvest-dropped.csv')
            if source_site else None
        )
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
                self._harvested.append({'url': url})

    def closed(self, reason):
        out_dir = os.path.dirname(self._harvest_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(self._harvest_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=['url'])
            writer.writeheader()
            writer.writerows(self._harvested)

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
