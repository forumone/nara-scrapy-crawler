import csv
import os
from urllib.parse import urlparse

from scrapy.linkextractors import LinkExtractor

from archive_crawler import exclusion_rules as _exclusion_rules_module

# Shared by _census_links across every spider that mixes in
# ExclusionLoggingMixin - stateless/config-only, safe to reuse. No
# allow_domains (we want external domains surfaced, not dropped) and
# deny_extensions=() (no IGNORED_EXTENSIONS - our own is_web_url is the sole
# authority on what's web-shaped). Scrapy's own _is_valid_url still silently
# drops non-http(s)/file/ftp schemes (mailto:/tel:/javascript:) with no way
# to override that - accepted as out of scope for the census, since these
# are a small enough share of overall link volume not to matter for
# explaining a page-count gap at the client's claimed scale.
_CENSUS_LINK_EXTRACTOR = LinkExtractor(deny_extensions=())


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
    their own identical `_get_exclusion_rules`/`_log_exclusion`/`closed()`.

    Two separate logs, kept in separate files so `scrape + exclude =
    harvest` holds exactly for a NavHarvesterMixin-based spider's harvest
    CSV:

    - `_log_exclusion`/`*_exclusions.csv`: a URL that *was* counted into
      `*_harvest.csv` - a real harvest row already existed for it - then
      rejected, post-fetch or post-harvest-row. Every row here corresponds
      to a URL that added one row to the harvest CSV.
    - `_log_dropped`/`*_dropped.csv`: anything rejected *before* a harvest
      row would ever exist for it, regardless of which code path found it -
      `_census_links`'s own wide, non-following sweep of every same-domain
      href on a page (built to audit total sitewide hyperlink volume, not
      to decide what the crawl follows), and `rules:` matches found via the
      crawl's real, narrow link-following (`_apply_exclusion_rules`) alike.
      A URL logged here was never a harvest-candidate in the first place,
      so it isn't expected to reconcile against the harvest CSV at all.
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

    def _census_links(self, response):
        """Extract every <a>/<area> href on the page via a wide-open
        LinkExtractor (deny_extensions=() - see _CENSUS_LINK_EXTRACTOR) and
        log one of each URL's first occurrence under a widened reason set:
        this domain's rules: matches (the existing mechanism, now applied to
        every link on the page rather than just the ones a Rule's own
        LinkExtractor happened to extract) and non-web extensions.
        External-domain links are silently dropped, not logged - a naive
        mirror tool wouldn't plausibly "forget" to exclude other domains
        either, so this bucket isn't useful signal for explaining a
        same-domain page-count gap and would only inflate the log. Also does
        NOT see mailto:/tel:/javascript: links - Scrapy's own _is_valid_url
        drops any non-http(s)/file/ftp scheme unconditionally, with no way
        to override that short of bypassing LinkExtractor entirely, which
        isn't worth it for a share of link volume this small either.

        Built to make total site-wide hyperlink volume auditable against a
        client's page-count claim by reason - not to expand what gets
        crawled. Logs every reason via _log_dropped, not _log_exclusion -
        none of these URLs were ever real harvest-candidates (see class
        docstring), so they belong in *_dropped.csv, not *_exclusions.csv -
        the same bucket _apply_exclusion_rules' own rules: matches land in,
        for the same reason. Never schedules a Request for anything found
        here; this is extraction + classification only.

        Returns the URLs that don't fall into any of those buckets (real,
        same-domain, non-rule-excluded, HTML-shaped links) for callers that
        need a further check of their own - e.g. ArchiveSpiderMixin comparing
        against its own seed list to find content-page links never reached
        by nav/listing harvesting at all.
        """
        rules = self._get_exclusion_rules()
        allowed = set(d.lower() for d in (getattr(self, 'allowed_domains', None) or []))
        response_base = response.url.split('#', 1)[0]
        kept = []
        for link in _CENSUS_LINK_EXTRACTOR.extract_links(response):
            url = link.url
            if url.split('#', 1)[0] == response_base:
                continue
            host = urlparse(url).netloc.split(':')[0].lower()
            if allowed and host not in allowed:
                continue
            reason = _exclusion_rules_module.match_exclude(url, rules)
            if reason is not None:
                self._log_dropped(url, reason)
                continue
            if not _exclusion_rules_module.is_web_url(url, rules):
                ext = _exclusion_rules_module.url_extension(url)
                self._log_dropped(url, f'extension:{ext}')
                continue
            kept.append(url)
        return kept
