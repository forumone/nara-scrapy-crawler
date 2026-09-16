"""Post-crawl health check against a site's *_dropped.csv reason log.

http_5xx and network_error:* rows there (written by
ExclusionLoggingMixin._log_http_error, via archive_crawler/spiders/base.py)
mean the crawl could not reach some or all of the live site during this
run. Pushing a CSV built under those conditions risks the index-side
Lambda's mark-and-sweep reconciliation (see push.py) removing documents for
URLs that are still real content, just unreachable this run - not actually
gone from the site.

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


class CrawlHealthError(ValueError):
    pass


def _dropped_path(csv_path):
    return csv_path.rsplit('.', 1)[0] + '_dropped.csv'


def count_fetch_errors(csv_path):
    """Count http_5xx/network_error rows in csv_path's sibling dropped-log.
    Returns 0 if that file does not exist."""
    dropped_path = _dropped_path(csv_path)
    if not os.path.exists(dropped_path):
        return 0
    count = 0
    with open(dropped_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            reason = row.get('reason', '')
            if reason == _HTTP_5XX_REASON or reason.startswith(_NETWORK_ERROR_PREFIX):
                count += 1
    return count


def check_crawl_health(source_site, csv_path, threshold):
    """Raise CrawlHealthError if csv_path's dropped-log has at least
    `threshold` http_5xx/network_error rows - signals the site, or the
    network path to it, was unreachable for at least part of this crawl,
    not just that individual pages were excluded by content rules."""
    count = count_fetch_errors(csv_path)
    if count >= threshold:
        raise CrawlHealthError(
            f"{source_site}: {count} http_5xx/network_error row(s) in "
            f"{_dropped_path(csv_path)} (threshold {threshold}). The site "
            f"or network may have been unreachable during this crawl. "
            f"Pass --bypass to push anyway."
        )
