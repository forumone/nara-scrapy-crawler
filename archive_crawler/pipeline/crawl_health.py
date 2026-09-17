"""Post-crawl health check against a site's *_dropped.csv reason log.

http_5xx and network_error:* rows there (written by
ExclusionLoggingMixin._log_http_error, via archive_crawler/spiders/base.py)
mean the crawl could not reach some or all of the live site during this
run. Both mean the same thing for this check: pushing a CSV built under
those conditions risks the index-side Lambda's mark-and-sweep
reconciliation (see push.py) removing documents for URLs that are still
real content, just not fetched correctly this run.

EmptyResponseGuardMiddleware (archive_crawler/middlewares.py) raises for
a 0-byte body that otherwise looks like a normal response - confirmed
live 2026-09-16 on trumpwhitehouse (a stale/broken CloudFront edge cache
entry) and, separately, confirmed widespread and persistent - the same
URLs, unchanged for months - on several Clinton-era sites' ordinary
content pages. That second case is deliberately NOT counted here:
threshold-based abort assumes a failure eventually resolves so a later
crawl gets through cleanly; a permanently-empty page never resolves, so
counting it would abort every future push for that site, forever,
requiring a manual --bypass on every single run - worse than the
problem it would guard against. network_error:EmptyResponseError is
logged (visible for manual review) but excluded from this count.

network_error:EmptyPaginationResponseError - the same 0-byte condition,
but on a NavHarvesterMixin._walk_listing_pagination request - IS
counted. A dead pager-continuation page costs everything past it in that
listing's chain, not just the one page, and this failure mode has no
evidence of being persistent the way the content-leaf case is.

network_error:EmptySitemapResponseError - the same 0-byte condition, but
on an ArchiveSpiderMixin._parse_sitemap request (the top-level sitemap
index or one of its sub-sitemaps) - IS counted, for the same reason as
the pagination case above: a lost sub-sitemap silently drops every URL
it would have listed, with nothing else to flag it, since the site's
other sub-sitemaps still produce a nonzero CSV that validate.py's
zero-row check would not catch.

A missing dropped-log (a site not yet re-crawled since this check was
added, or a hand-built --csv unrelated to any crawl) is treated as 0
errors, not a hard failure - the zero-row check in validate.py and the
Lambda's own empty-scope guard already cover the case where nothing at all
came back.
"""
import csv
import os

_NETWORK_ERROR_PREFIX = 'network_error:'
_HTTP_5XX_REASON = 'http_5xx'
_EXCLUDED_REASONS = frozenset({'network_error:EmptyResponseError'})


class CrawlHealthError(ValueError):
    pass


def _dropped_path(csv_path):
    return csv_path.rsplit('.', 1)[0] + '_dropped.csv'


def count_fetch_errors(csv_path):
    """Count http_5xx/network_error rows in csv_path's sibling
    dropped-log, except _EXCLUDED_REASONS (see module docstring). Returns
    0 if that file does not exist."""
    dropped_path = _dropped_path(csv_path)
    if not os.path.exists(dropped_path):
        return 0
    count = 0
    with open(dropped_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            reason = row.get('reason', '')
            if reason in _EXCLUDED_REASONS:
                continue
            if reason == _HTTP_5XX_REASON or reason.startswith(_NETWORK_ERROR_PREFIX):
                count += 1
    return count


def check_crawl_health(source_site, csv_path, threshold):
    """Raise CrawlHealthError if csv_path's dropped-log has at least
    `threshold` http_5xx/network_error rows - signals the site, or the
    network path to it, was unreachable or returned broken responses for
    at least part of this crawl, not just that individual pages were
    excluded by content rules."""
    count = count_fetch_errors(csv_path)
    if count >= threshold:
        raise CrawlHealthError(
            f"{source_site}: {count} http_5xx/network_error "
            f"row(s) in {_dropped_path(csv_path)} (threshold {threshold}). "
            f"The site or network may have been unreachable during this "
            f"crawl. Pass --bypass to push anyway."
        )
