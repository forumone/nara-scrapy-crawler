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

    Previously duplicated: ArchiveSpiderMixin and NavHarvesterMixin each
    defined their own identical _get_exclusion_rules, and only
    ArchiveSpiderMixin had _log_exclusion/closed() at all - meaning nav and
    listing harvesters had no way to log what they chose not to
    follow/yield. Factored out here so all three compose it instead of
    tripling that duplication.

    EXCLUSIONS_FILE_SUFFIX defaults to 'exclusions' (ArchiveSpiderMixin's
    existing filename, unchanged) - override per mixin/spider so a nav
    harvester, a listing harvester, and a content spider sharing the same
    SOURCE_SITE don't overwrite each other's exclusion log when run back to
    back (e.g. NavHarvesterMixin sets 'nav-exclusions').
    """

    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

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

    def closed(self, reason):
        exclusions = getattr(self, '_exclusions', [])
        if not exclusions:
            return
        # -a exclusions_file=<path> overrides the derived default - no
        # explicit __init__ parameter needed for this, since plain
        # scrapy.Spider.__init__ already assigns any unrecognized -a kwarg
        # as an instance attribute.
        out_path = getattr(self, 'exclusions_file', None)
        if not out_path:
            out_dir = os.path.join('data', self.SOURCE_SITE)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f'{self.SOURCE_SITE}_{self.EXCLUSIONS_FILE_SUFFIX}.csv')
        else:
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['url', 'reason'])
            writer.writeheader()
            writer.writerows(exclusions)

    def _census_links(self, response):
        """Extract every <a>/<area> href on the page via a wide-open
        LinkExtractor (deny_extensions=() - see _CENSUS_LINK_EXTRACTOR) and
        log one of each URL's first occurrence under a widened reason set:
        this domain's rules:/nav_deny matches (the existing mechanism, now
        applied to every link on the page rather than just the ones a Rule's
        own LinkExtractor happened to extract) and non-web extensions.
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
        crawled. Never schedules a Request for anything found here; this is
        extraction + classification only.

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
                self._log_exclusion(url, reason)
                continue
            if not _exclusion_rules_module.is_web_url(url, rules):
                ext = _exclusion_rules_module.url_extension(url)
                self._log_exclusion(url, f'extension:{ext}')
                continue
            kept.append(url)
        return kept
