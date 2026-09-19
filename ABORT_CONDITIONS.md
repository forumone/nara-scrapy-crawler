# Abort Conditions

This document covers every condition that stops a crawl early, or
blocks a push, and why each one exists. Two separate mechanisms are
involved: a crawl-time circuit breaker, inside the spider itself, and a
set of push-time checks, inside `scrape_index_pipeline`.

## Crawl-time: the timeout circuit breaker

`DOWNLOAD_TIMEOUT`/`RETRY_TIMES` bound how long one request can spend
failing before Scrapy gives up on it for good. Once that happens, the
final failure reaches one of three errback methods, based on the kind
of request it was.

**Content-page request.** A running count tracks how many content-page
requests, on the current crawl, have exhausted every retry with a real
`twisted.internet.error.TimeoutError`. At `CONTENT_LEAF_TIMEOUT_THRESHOLD`
occurrences, the spider closes outright, with `finish_reason`
`content_leaf_timeout_threshold`. Below that count, each timeout logs
as an ordinary dropped row and the crawl continues. Only a genuine
timeout counts toward this. A site could return a real HTTP error, or a
connection-refused error, for every single request, and this count
would stay at zero, since neither condition is a timeout.

**Sitemap or listing-pagination-continuation request.** The same
exhausted-retry timeout, on either of these two request kinds, closes
the spider immediately, on the first occurrence, with `finish_reason`
`critical_sitemap_timeout` or `critical_pagination_timeout`. No count
is kept here, unlike the content-page case. A single lost sitemap
request drops every URL it would have listed, and a single lost
pagination-continuation request drops every page past it in that
listing's chain - either one costs far more than one page, so waiting
for a second occurrence would already be too late.

A crawl that closes this way still runs its normal shutdown. Every row
logged before the close, and the close itself, get written to
`*_dropped.csv` as usual.

## Push-time: the checks in `scrape_index_pipeline`

`push` and `crawl-and-push` run four checks, in order, before uploading
anything. The first three never skip, not even with `--bypass`. Only
the fourth does.

### 1. Zero rows in the main CSV

A CSV with zero data rows always aborts. A crawl could return no rows
for several different reasons, a crash before any page was scraped, a
`--csv` path pointing at the wrong file, or a genuine, sitewide network
or server outage. None of those should ever reach the index. A
downstream reconciliation step that treats "this push" as "the current
state of the site" must never be handed a push that says the site now
has zero pages, when the truth is that this run simply produced
nothing.

### 2. A missing dropped-log

If `*_dropped.csv` does not exist at all, the push aborts. The spider
writes this file on every clean shutdown, even when it has nothing to
report - it is a zero-row file in that case, not a missing one. A
missing file means the process ended before that write happened: an
out-of-memory kill, a crash, a forcibly terminated session, anything
that skips a normal shutdown. A crash like this can still leave a real,
partial main CSV behind, since output is written incrementally as
pages are scraped, so the zero-row check above would not catch it. A
missing dropped-log is the signal that does.

### 3. A critical dropped-log row

Any row logged under `critical_sitemap:` or `critical_pagination:`
aborts the push, on its own, regardless of how many or how few there
are. Both prefixes cover a lost sitemap or listing-pagination-
continuation request - the same category the crawl-time circuit
breaker above treats as disqualifying, whatever the underlying failure
was, a real server error, a real network error, or an empty response
that otherwise looked like a normal page. One such row means part of
the site was never actually discovered this run, not that one page
happened to fail.

A plain HTTP 404 on either kind of request is the one exception, and
does not fall under either prefix. A 404 means the resource genuinely
does not exist, not that the crawl lost access to it. Unlike a real
fetch failure, a 404 does not resolve itself on a later run, so
treating it as disqualifying would make every future push impossible
without an override, forever, over a condition that was never going to
change.

### 4. Too many ordinary fetch failures

`http_5xx` and `network_error:*` rows on an ordinary content-page fetch
count toward `--error-threshold`. At or past that count, the push
aborts. Below it, the push proceeds. One isolated page-level failure,
on its own, costs only that one page - but enough of them together
signal the site, or the network path to it, was unreachable for at
least part of the run. Pushing that data as-is risks a downstream
reconciliation step reading every unfetched page as though it had been
removed from the live site, rather than simply missed this run.

The default threshold comes from the site's own configuration, not a
fixed global number. A site can set its own default higher or lower
than the project default of 1. Passing `--error-threshold` on the
command line always overrides whatever default applies.

One specific reason is excluded from this count entirely:
`network_error:EmptyResponseError`. On some sites this condition is
transient, and a later crawl clears it. On others, it turns up on the
same URLs indefinitely - a permanently broken page, not a temporary
outage. Counting it would abort every future push for a site in that
second category, forever, requiring a manual override on every single
run. Excluding it, and logging it for manual review instead, avoids
that outcome without hiding the condition entirely.

`--bypass` skips only this fourth check. It never skips the zero-row
check, the missing-dropped-log check, or the critical-row check.
