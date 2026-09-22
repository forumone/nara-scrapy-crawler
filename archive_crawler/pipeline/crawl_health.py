"""Post-crawl health check against a site's *_dropped.csv reason log.

Every reason this check looks at falls into one of three groups.

Group 1, excluded, never counts toward anything:
network_error:EmptyResponseError. EmptyResponseGuardMiddleware (archive_
crawler/middlewares.py) raises it for a 0-byte body that otherwise looks
like a normal response, on an ordinary content-page request. On some
sites this reason is transient; on others it turns up on the same URLs
indefinitely, a permanently broken page rather than a temporary outage.
Threshold-based abort assumes a failure eventually resolves, so a later
crawl gets through cleanly. A permanently-empty page never resolves that
way, so counting it would abort every future push for that site,
forever, requiring a manual --bypass on every single run - worse than
the problem it would guard against. It is logged, for manual review, but
never counted here.

Group 2, counted toward --error-threshold, skipped by --bypass:
http_5xx and network_error:* rows on an ordinary content-page fetch
(written by ArchiveSpiderMixin._log_http_error/NavHarvesterMixin.
_log_nav_fetch_error). Each one means one page did not come back this
run. A partial outage can leave real, nonzero rows behind while sweeping
away every URL that failed to fetch, so this check exists at all - but
losing one ordinary page, on its own, does not cost any other page.

Group 3, critical, always aborts, ignores --error-threshold and
--bypass alike: every critical_sitemap:*, critical_pagination:*, and
critical_timeout_threshold reason. ArchiveSpiderMixin._log_sitemap_fetch_error
(base.py) logs the first, for a failed top-level sitemap or sub-sitemap
request. NavHarvesterMixin._log_pagination_fetch_error (nav_harvest.py)
logs the second, for a failed listing-pagination continuation request.
Both cover a real server error, a real network error, and the matching
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

ArchiveSpiderMixin._log_http_error (base.py) logs the third,
critical_timeout_threshold, once CONTENT_PAGE_TIMEOUT_THRESHOLD ordinary
content-page timeouts close the spider outright. This one carries no
per-row sub-reason, since it marks a single aggregate event, not one
failed request - CONTENT_PAGE_TIMEOUT_THRESHOLD and --error-threshold
are two independent settings, for two independent jobs, and neither
should have to be tuned to stay above the other for this circuit
breaker to mean anything at push time.

A plain HTTP 404 on either kind of request is excluded from this group
on purpose, logged as ordinary http_404 instead. A 404 means the
resource does not exist, not that the crawl lost access to it. Unlike a
5xx or a network error, a 404 never resolves on a later run, so
counting it here would abort every future push for that site, forever -
the same reasoning Group 1's network_error:EmptyResponseError exclusion
already rests on.

That same property - a 404 is the one dropped-log reason that means a
URL is actually gone, rather than merely unreached this run - is also
what find_confirmed_deletions() below relies on. convert.py uses its
result to tombstone those URLs explicitly in the pushed JSONL, rather
than leaving the downstream Lambda to infer deletion from a URL's plain
absence, which cannot tell a real 404 apart from a transient failure
(see ABORT_CONDITIONS.md and ARCHITECTURE.md's "Push pipeline stages").
Every other dropped-log reason - Group 1, Group 2, and Group 3 alike -
means the crawl simply never confirmed the URL's current state, so none
of them tombstone anything; the existing index entry is left alone.

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
_CONFIRMED_DELETE_REASON = 'http_404'


class CrawlHealthError(ValueError):
    pass


def _dropped_path(csv_path):
    return csv_path.rsplit('.', 1)[0] + '_dropped.csv'


def _exclusions_path(csv_path):
    return csv_path.rsplit('.', 1)[0] + '_exclusions.csv'


def _read_dropped_rows(csv_path):
    """Return every row (url + reason) in csv_path's sibling dropped-log,
    or an empty list if that file does not exist (see module docstring)."""
    dropped_path = _dropped_path(csv_path)
    if not os.path.exists(dropped_path):
        return []
    with open(dropped_path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _read_dropped_reasons(csv_path):
    """Return every `reason` value in csv_path's sibling dropped-log, or
    an empty list if that file does not exist (see module docstring)."""
    return [row.get('reason', '') for row in _read_dropped_rows(csv_path)]


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
    critical_sitemap:*/critical_pagination:* reason (a lost sitemap or
    listing-pagination-continuation request), or critical_timeout_threshold
    (the crawl-time content-page timeout circuit breaker tripped). Returns
    an empty list if the dropped-log does not exist or holds none."""
    return [reason for reason in _read_dropped_reasons(csv_path) if reason.startswith(_CRITICAL_PREFIX)]


def find_confirmed_deletions(csv_path):
    """Return every URL in csv_path's sibling dropped-log logged as a
    plain http_404 - see the module docstring's note right after the
    Group 3 discussion for why this, alone among every dropped-log
    reason, means the URL is confirmed gone rather than merely unreached
    this run. Returns an empty list if the dropped-log does not exist or
    holds none. Does not require check_crawl_health to have passed first
    - a 404 carries the same meaning whether or not this run's
    ordinary-failure count trips --error-threshold."""
    return [row['url'] for row in _read_dropped_rows(csv_path) if row.get('reason') == _CONFIRMED_DELETE_REASON]


def find_excluded_urls(csv_path):
    """Every URL in csv_path's sibling exclusions-log, regardless of
    reason - an exclusion rule match is a deliberate editorial signal,
    at least as authoritative as a confirmed 404. Unlike
    find_confirmed_deletions, this reads *_exclusions.csv, not
    *_dropped.csv - a url_pattern:/extension:/rules: match happens
    before a harvest row ever exists for the URL (see
    ExclusionLoggingMixin's own docstring), so it never appears in the
    dropped-log at all. Returns an empty list if the exclusions-log does
    not exist or holds none. Independent of check_crawl_health, same as
    find_confirmed_deletions - an exclusion match carries the same
    meaning regardless of this run's ordinary-failure count."""
    path = _exclusions_path(csv_path)
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        return [row['url'] for row in csv.DictReader(f)]


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
            f"just one page, and a tripped timeout circuit breaker means "
            f"the crawl itself gave up early. This check has no --bypass."
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
