"""Post-crawl health check against a site's *_dropped.csv reason log.

Every reason this check looks at falls into one of three groups.

Group 1, excluded, never counts toward anything:
network_error:EmptyResponseError. EmptyResponseGuardMiddleware (archive_
crawler/middlewares.py) raises it for a 0-byte body that otherwise looks
like a normal response, on an ordinary content-page request. Confirmed
live 2026-09-16 on trumpwhitehouse (a stale/broken CloudFront edge cache
entry) and, separately, confirmed widespread and persistent - the same
URLs, unchanged for months - on several Clinton-era sites' ordinary
content pages. Threshold-based abort assumes a failure eventually
resolves, so a later crawl gets through cleanly. A permanently-empty page
never resolves that way, so counting it would abort every future push
for that site, forever, requiring a manual --bypass on every single run -
worse than the problem it would guard against. It is logged, for manual
review, but never counted here.

Group 2, counted toward --error-threshold, skipped by --bypass:
http_5xx and network_error:* rows on an ordinary content-page fetch
(written by ArchiveSpiderMixin._log_http_error/NavHarvesterMixin.
_log_nav_fetch_error). Each one means one page did not come back this
run. A partial outage can leave real, nonzero rows behind while sweeping
away every URL that failed to fetch, so this check exists at all - but
losing one ordinary page, on its own, does not cost any other page.

Group 3, critical, always aborts, ignores --error-threshold and
--bypass alike: every critical_sitemap:* and critical_pagination:*
reason. ArchiveSpiderMixin._log_sitemap_fetch_error (base.py) logs the
first, for a failed top-level sitemap or sub-sitemap request.
NavHarvesterMixin._log_pagination_fetch_error (nav_harvest.py) logs the
second, for a failed listing-pagination continuation request. Both
cover a real server error, a real network error, and the matching
empty-response special case (EmptySitemapResponseError/
EmptyPaginationResponseError) alike - the reason string carries the
detail, but every one of them lands in this group. A lost sub-sitemap
drops every URL it would have listed, with nothing else to flag it,
since the site's other sub-sitemaps still produce a nonzero CSV that
validate.py's zero-row check would not catch. A lost pagination
continuation page costs every page past it in that listing's chain, the
same way. Neither failure is safe to average against a threshold meant
for isolated, one-page losses, so a single row in this group always
raises, with no override.

A missing dropped-log always raises, unconditionally, the same as a
Group 3 row - --bypass does not skip this either. ExclusionLoggingMixin
writes *_dropped.csv on every clean spider_closed, even with zero data
rows (see its own docstring). The one thing that skips that write is a
crash: an OOM kill, a segfault, a killed SSH session, anything that
ends the process before spider_closed fires. A crashed crawl can still
leave a real, nonzero main CSV behind, since FEEDS writes rows as they
get scraped, not only at the end - so validate.py's zero-row check does
not catch this case either. Before this check existed, a crashed run's
missing dropped-log read as zero errors, the same as a clean run, and a
partial crawl could reach push looking like a smaller, ordinary one. A
hand-built --csv with no matching dropped-log, previously tolerated
here, now needs a placeholder dropped-log (header row, zero data rows)
alongside it. --bypass does not create that exception either, the
deliberate trade for closing the crash gap.
"""
import csv
import os

_NETWORK_ERROR_PREFIX = 'network_error:'
_HTTP_5XX_REASON = 'http_5xx'
_EXCLUDED_REASONS = frozenset({'network_error:EmptyResponseError'})
_CRITICAL_PREFIX = 'critical_'


class CrawlHealthError(ValueError):
    pass


def _dropped_path(csv_path):
    return csv_path.rsplit('.', 1)[0] + '_dropped.csv'


def _read_dropped_reasons(csv_path):
    """Return every `reason` value in csv_path's sibling dropped-log, or
    an empty list if that file does not exist (see module docstring)."""
    dropped_path = _dropped_path(csv_path)
    if not os.path.exists(dropped_path):
        return []
    with open(dropped_path, newline='', encoding='utf-8') as f:
        return [row.get('reason', '') for row in csv.DictReader(f)]


def count_fetch_errors(csv_path):
    """Count Group 2 rows in csv_path's sibling dropped-log: http_5xx/
    network_error rows that count toward --error-threshold. Excludes
    Group 1 (_EXCLUDED_REASONS) and Group 3 (any critical_-prefixed
    reason - see find_critical_errors) alike. Returns 0 if the
    dropped-log does not exist."""
    count = 0
    for reason in _read_dropped_reasons(csv_path):
        if reason in _EXCLUDED_REASONS or reason.startswith(_CRITICAL_PREFIX):
            continue
        if reason == _HTTP_5XX_REASON or reason.startswith(_NETWORK_ERROR_PREFIX):
            count += 1
    return count


def find_critical_errors(csv_path):
    """Return every Group 3 row in csv_path's sibling dropped-log: a
    critical_sitemap:*/critical_pagination:* reason, meaning a lost
    sitemap or listing-pagination-continuation request. Returns an empty
    list if the dropped-log does not exist or holds none."""
    return [reason for reason in _read_dropped_reasons(csv_path) if reason.startswith(_CRITICAL_PREFIX)]


def check_crawl_health(source_site, csv_path, threshold, bypass=False):
    """Raise CrawlHealthError for any of three reasons.

    First, unconditionally: csv_path's dropped-log does not exist at
    all. --bypass does not skip this check.

    Second, unconditionally: the dropped-log holds at least one Group 3
    (critical_) row. --bypass does not skip this check either.

    Third, only when bypass is False: the dropped-log holds at least
    `threshold` Group 2 (http_5xx/network_error) rows. --bypass skips
    only this third check.

    See the module docstring for the full three-group split, and why a
    missing dropped-log is no longer treated as zero errors."""
    dropped_path = _dropped_path(csv_path)
    if not os.path.exists(dropped_path):
        raise CrawlHealthError(
            f"{source_site}: {dropped_path} does not exist. Either this "
            f"site has never been crawled through this project's own "
            f"spiders, or the crawl that produced {csv_path} crashed "
            f"before writing it. This check has no --bypass. A hand-built "
            f"CSV needs a placeholder dropped-log (header row, zero data "
            f"rows) alongside it."
        )
    critical = find_critical_errors(csv_path)
    if critical:
        detail = ', '.join(sorted(set(critical)))
        raise CrawlHealthError(
            f"{source_site}: {len(critical)} critical fetch failure(s) in "
            f"{_dropped_path(csv_path)} ({detail}). A lost sitemap or "
            f"listing-pagination request costs every page past it, not "
            f"just one page. This check has no --bypass."
        )
    if bypass:
        return
    count = count_fetch_errors(csv_path)
    if count >= threshold:
        raise CrawlHealthError(
            f"{source_site}: {count} http_5xx/network_error "
            f"row(s) in {_dropped_path(csv_path)} (threshold {threshold}). "
            f"The site or network may have been unreachable during this "
            f"crawl. Pass --bypass to push anyway."
        )
