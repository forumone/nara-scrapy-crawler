import csv
import os

import scrapy

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
    SOURCE_SITE, regardless of spider type.

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
      `pagination_listing_page`). Also `spider_exception:*` - an uncaught
      exception in this project's own parsing code, caught project-wide by
      middlewares.py's UnhandledSpiderExceptionLoggingMiddleware, logged
      here instead of only a console traceback. `scrape + drop = harvest`
      holds against this file exactly.

    Both files are written on every run, even with zero rows (header
    only) - a stale file from a prior run never survives a run that had
    nothing to log. scrape_index_pipeline's crawl_health check relies on
    this to read *_dropped.csv as this run's own record, not leftover
    state from whenever the site last had a fetch failure.

    Both are also deleted, if present, at spider_opened, before this run
    writes anything of its own - see _delete_stale_logs. That write-on-
    close plus delete-on-open pair together guarantee the file's mere
    presence, after this run, is honest evidence this run reached a
    clean spider_closed. A crash leaves it genuinely missing, not the
    previous run's file mistaken for this one's.
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

    def _log_path(self, file_attr, suffix):
        # -a exclusions_file=<path>/-a dropped_file=<path> overrides the
        # derived default - no explicit __init__ parameter needed for
        # this, since plain scrapy.Spider.__init__ already assigns any
        # unrecognized -a kwarg as an instance attribute. Shared by
        # _write_log and _delete_stale_logs, so both always agree on
        # exactly which path they mean.
        out_path = getattr(self, file_attr, None)
        if not out_path:
            return os.path.join('data', self.SOURCE_SITE, f'{self.SOURCE_SITE}_{suffix}.csv')
        return out_path

    def _write_log(self, rows, file_attr, suffix):
        # Always write, even with zero rows - a downstream consumer (e.g.
        # scrape_index_pipeline's crawl_health check) reads this file to
        # judge THIS run's health. Skipping the write on an empty run would
        # leave a prior run's file in place, making a healthy re-crawl look
        # like it still has that old run's dropped rows.
        out_path = self._log_path(file_attr, suffix)
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'reason'])
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        # Runs the delete on spider_opened, not __init__ - SOURCE_SITE and
        # any -a dropped_file=<path> override are both guaranteed set by
        # then, and this fires once, before start_requests yields anything.
        # Nothing else in this project connects a signal manually; every
        # other hook (closed()) rides Scrapy's own automatic spider_closed
        # dispatch. spider_opened has no equivalent auto-dispatch, so this
        # is the one place that needs an explicit crawler.signals.connect.
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider._delete_stale_logs, signal=scrapy.signals.spider_opened)
        return spider

    def _delete_stale_logs(self):
        """Delete *_exclusions.csv/*_dropped.csv, if either already exists,
        before this run writes anything of its own.

        closed() only runs on a clean spider_closed - a crash (an OOM
        kill, a segfault, a killed SSH session) skips it entirely, and
        the file from this run's *predecessor* stays on disk untouched,
        looking exactly like a valid record of this run.
        scrape_index_pipeline's crawl_health check now requires
        *_dropped.csv to exist and treats a missing one as an
        unconditional abort (see crawl_health.py's module docstring) -
        without this delete, a crashed re-crawl's stale, leftover file
        would still exist, and that abort would never fire. Deleting it
        here first means a crash produces a genuinely missing file, not
        a misleadingly present one, and the existing crawl_health check
        catches it without needing to inspect finish_reason at all."""
        for file_attr, suffix in (
            ('exclusions_file', self.EXCLUSIONS_FILE_SUFFIX),
            ('dropped_file', self.DROPPED_FILE_SUFFIX),
        ):
            path = self._log_path(file_attr, suffix)
            if os.path.exists(path):
                os.remove(path)

    def closed(self, reason):
        self._write_log(getattr(self, '_exclusions', []), 'exclusions_file', self.EXCLUSIONS_FILE_SUFFIX)
        self._write_log(getattr(self, '_dropped', []), 'dropped_file', self.DROPPED_FILE_SUFFIX)
