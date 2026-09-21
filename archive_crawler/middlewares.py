"""Project-wide spider middleware - see settings.py's SPIDER_MIDDLEWARES."""


class EmptyResponseError(ValueError):
    pass


class EmptyPaginationResponseError(EmptyResponseError):
    """Same 0-byte-body condition as EmptyResponseError, but on a
    NavHarvesterMixin._walk_listing_pagination request specifically - a
    dead pager-continuation page costs everything past it in that
    listing's chain (see nav_harvest.py), not just the one page a
    content-page failure costs. crawl_health.py counts this reason but
    not plain EmptyResponseError - see that module for why."""
    pass


class EmptySitemapResponseError(EmptyResponseError):
    """Same 0-byte-body condition as EmptyResponseError, but on an
    ArchiveSpiderMixin._parse_sitemap request - the top-level sitemap
    index or one of its listed sub-sitemaps. Losing a sub-sitemap loses
    every URL it would have listed, silently, with no per-URL retry or
    record beyond this one row - the same cascading shape
    EmptyPaginationResponseError already covers for a dead
    pager-continuation page, not a single content-page loss.
    crawl_health.py counts this reason but not plain
    EmptyResponseError - see that module for why."""
    pass


class EmptyResponseGuardMiddleware:
    """Raise EmptyResponseError (or EmptyPaginationResponseError on a
    pagination-continuation request, or EmptySitemapResponseError on a
    sitemap/sub-sitemap request) for a response that would otherwise
    reach a callback normally (status 200, or another status a spider
    has explicitly opted into via handle_httpstatus_list) but has a
    0-byte body.

    CloudFront can serve a genuinely empty body on a 200 response, from
    a stale/broken edge cache entry - on some sites a one-off, on
    others a persistent condition on the same URLs for months. That
    response passes every existing
    check (not a network error, not an HTTP error, a real TextResponse)
    and reaches _scrape_item, where it silently produces a
    no_body/no_title row - exactly the content some sites'
    filter_rules/<source_site>.yml drops before push, which then reads
    as a deletion to the downstream Lambda's mark-and-sweep.

    Raising here, before any callback ever sees the response, sends it
    to the failing request's own errback - Scrapy's call_spider() hands
    a process_spider_input failure straight to request.errback when one
    is set (scrapy/core/scraper.py), before any spider middleware's
    process_spider_exception gets a look, and every real spider in this
    project sets one. That errback classifies it the same way it
    classifies a DNS failure: network_error:<this class's name> in
    *_dropped.csv.

    Ordered after HttpErrorMiddleware (priority 50 in settings.py) in
    SPIDER_MIDDLEWARES, so a real 404/3xx/5xx never reaches this check at
    all - only a response HttpErrorMiddleware already treated as normal.
    """

    def process_spider_input(self, response, spider):
        if response.body:
            return
        callback_name = getattr(getattr(response.request, 'callback', None), '__name__', '')
        if callback_name == '_walk_listing_pagination':
            raise EmptyPaginationResponseError(
                f'0-byte response body on a pagination-continuation page: {response.url}')
        if callback_name == '_parse_sitemap':
            raise EmptySitemapResponseError(
                f'0-byte response body on a sitemap/sub-sitemap request: {response.url}')
        raise EmptyResponseError(f'0-byte response body: {response.url}')


class UnhandledSpiderExceptionLoggingMiddleware:
    """Log any uncaught exception raised while processing a response, from
    any callback (parse_nav, NavHarvesterMixin._walk_listing_pagination,
    any spider's own _scrape_item/_parse_generic/_parse_dataset) or an
    earlier spider middleware.

    Scrapy already contains a crash like this to the one response - the
    crawl continues on to other requests either way. Without this
    middleware, the only trace is a console/log "Spider error processing"
    traceback; nothing records it in *_dropped.csv, so it never shows up
    next to the http_5xx/network_error rows ArchiveSpiderMixin._log_http_error
    writes there (archive_crawler/spiders/base.py), and scrape_index_
    pipeline's crawl_health check (archive_crawler/pipeline/crawl_health.py)
    has no way to see it either.

    Logged as spider_exception:<ExceptionClassName> - a distinct prefix
    from http_5xx/network_error:*, since this is a bug in this project's
    own parsing code, not a network or server problem. crawl_health.py
    deliberately does not count spider_exception reasons toward its
    abort threshold; that threshold's message talks about the site/
    network being unreachable, which would misdescribe a parsing bug.
    EmptyResponseGuardMiddleware's own EmptyResponseError never reaches
    this class in practice - see that class's docstring for why.

    Returns an empty iterable, matching Scrapy's own default behavior of
    dropping the rest of a crashed callback's output - this does not
    recover anything the crashed callback would have gone on to schedule
    (e.g. _walk_listing_pagination's own next-page request). Containing
    that consequence needs a fix in that method itself, not here.
    """

    def process_spider_exception(self, response, exception, spider):
        log_dropped = getattr(spider, '_log_dropped', None)
        if log_dropped is not None:
            log_dropped(response.url, f'spider_exception:{type(exception).__name__}')
        # exc_info=True pulls from sys.exc_info(), which is not reliably
        # still set by the time this runs (Scrapy/Twisted's deferred
        # chain can leave this frame's exception context cleared,
        # logging "NoneType: None" instead of a real traceback).
        # Building the tuple explicitly from the exception object
        # itself (which still carries its own __traceback__) sidesteps
        # that.
        spider.logger.error(
            "Unhandled %s processing %s - logged as dropped, rest of this "
            "response's callback output is lost, crawl continues.",
            type(exception).__name__, response.url,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
        return []
