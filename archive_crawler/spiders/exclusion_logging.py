import csv
import os

from archive_crawler import exclusion_rules as _exclusion_rules_module


def _spider_exclusion_rules(spider):
    """Load (and cache) a spider's exclusion_rules.ExclusionRules.

    Shared by ArchiveSpiderMixin and NavHarvesterMixin - both require a
    SOURCE_SITE class attribute naming the archive_crawler/exclusion_rules/
    <SOURCE_SITE>.yml file to load. Reads -a rules_file=<path> and
    -a rules_mode=append|replace for a per-run override; neither the
    committed file nor rules_file is ever written to.
    """
    if not hasattr(spider, '_exclusion_rules_cache'):
        spider._exclusion_rules_cache = _exclusion_rules_module.load_rules(
            spider.SOURCE_SITE,
            getattr(spider, 'rules_file', None),
            getattr(spider, 'rules_mode', 'append'),
        )
    return spider._exclusion_rules_cache


class ExclusionLoggingMixin:
    """Shared exclusion-rule access + logging for any spider with a
    SOURCE_SITE, regardless of whether it's a content spider, a nav
    harvester, or a listing harvester.

    Factored out so a content spider, a nav harvester, and a listing
    harvester can each compose this one mixin instead of each defining
    their own identical `_get_exclusion_rules`/`_log_exclusion`/
    `_log_dropped`/`closed()`.

    Two separate logs, split by whether a harvest row exists for the URL:

    - `_log_exclusion`/`*_exclusions.csv`: a URL rejected *before* it was
      ever a harvest candidate - for `NavHarvesterMixin`
      (`_apply_exclusion_rules`), a `rules:`-matched link found via the
      crawl's real, narrow link-following, dropped before ever being
      requested; for a sitemap-based spider (`SitemapUrlSpiderMixin.
      _parse_sitemap`), a sitemap entry that failed the extension check or
      matched a `rules:` entry, dropped before a harvest row was ever
      written for it. No harvest row exists for anything logged here, so
      `*_exclusions.csv` never reconciles against the harvest CSV - for a
      sitemap-based spider, `harvest + exclude = sitemap total` instead.
    - `_log_dropped`/`*_dropped.csv`: a URL that already has a harvest
      row, then got rejected - post-fetch (a bad response: `frameset`,
      `non_text_response`, `redirect_wrapper`, `http_*`,
      `network_error:*`) or post-harvest-row (page fetched fine but judged
      non-content: `listing_page`, `search_listing_page`,
      `pagination_listing_page`). `scrape + drop = harvest` holds against
      this file exactly.
    """

    EXCLUSIONS_FILE_SUFFIX = 'exclusions'
    DROPPED_FILE_SUFFIX = 'dropped'

    def _get_exclusion_rules(self):
        return _spider_exclusion_rules(self)

    def _log_exclusion(self, url, reason):
        if not hasattr(self, '_exclusions'):
            self._exclusions = []
            self._logged_exclusion_urls = set()
        # Dedup by URL: a nav crawl can encounter the same excluded target
        # from many different referring pages (a sitewide-linked pattern, or
        # a url_list entry with many independent incoming links) - logging
        # every occurrence would bury the genuinely useful signal in
        # near-duplicate rows. Harmless for spiders that only ever consider
        # each URL once (e.g. the content spider reading a url_file), since
        # dedup never triggers there.
        if url in self._logged_exclusion_urls:
            return
        self._logged_exclusion_urls.add(url)
        self._exclusions.append({'url': url, 'reason': reason})

    def _log_dropped(self, url, reason):
        if not hasattr(self, '_dropped'):
            self._dropped = []
            self._logged_dropped_urls = set()
        if url in self._logged_dropped_urls:
            return
        self._logged_dropped_urls.add(url)
        self._dropped.append({'url': url, 'reason': reason})

    def _write_log(self, rows, file_attr, suffix):
        if not rows:
            return
        # -a exclusions_file=<path>/-a dropped_file=<path> overrides the
        # derived default - no explicit __init__ parameter needed for
        # this, since plain scrapy.Spider.__init__ already assigns any
        # unrecognized -a kwarg as an instance attribute.
        out_path = getattr(self, file_attr, None)
        if not out_path:
            out_dir = os.path.join('data', self.SOURCE_SITE)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f'{self.SOURCE_SITE}_{suffix}.csv')
        else:
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'reason'])
            writer.writeheader()
            writer.writerows(rows)

    def closed(self, reason):
        self._write_log(getattr(self, '_exclusions', []), 'exclusions_file', self.EXCLUSIONS_FILE_SUFFIX)
        self._write_log(getattr(self, '_dropped', []), 'dropped_file', self.DROPPED_FILE_SUFFIX)
