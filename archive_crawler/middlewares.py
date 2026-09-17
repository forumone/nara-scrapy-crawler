"""Project-wide spider middleware - see settings.py's SPIDER_MIDDLEWARES."""


class EmptyResponseError(ValueError):
    pass


class EmptyResponseGuardMiddleware:
    """Raise EmptyResponseError for a response that would otherwise reach
    a callback normally (status 200, or another status a spider has
    explicitly opted into via handle_httpstatus_list) but has a 0-byte
    body.

    Confirmed live 2026-09-16 against trumpwhitehouse, and confirmed
    widespread the same day on several Clinton-era sites: CloudFront can
    serve a genuinely empty body on a 200 response, from a stale/broken
    edge cache entry. That response passes every existing check (not a
    network error, not an HTTP error, a real TextResponse) and reaches
    _scrape_item, where it silently produces a no_body/no_title row -
    exactly the content some sites' filter_rules/<source_site>.yml drops
    before push, which then reads as a deletion to the downstream
    Lambda's mark-and-sweep. Raising here, before any callback ever sees
    the response, sends it to the failing request's own errback -
    Scrapy's call_spider() hands a process_spider_input failure straight
    to request.errback when one is set (scrapy/core/scraper.py), before
    any spider middleware's process_spider_exception gets a look, and
    every real spider in this project sets one. That errback classifies
    it the same way it classifies a DNS failure: logged as
    network_error:EmptyResponseError in *_dropped.csv, already counted by
    crawl_health.py's abort threshold via its existing network_error:*
    match - see count_fetch_errors. UnhandledSpiderExceptionLoggingMiddleware
    below only ever sees this for a spider with no errback wired
    anywhere, which does not describe anything in this project today.

    Ordered after HttpErrorMiddleware (priority 50 in settings.py) in
    SPIDER_MIDDLEWARES, so a real 404/3xx/5xx never reaches this check at
    all - only a response HttpErrorMiddleware already treated as normal.
    """

    def process_spider_input(self, response, spider):
        if not response.body:
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
        # chain can leave this frame's exception context cleared) -
        # confirmed live: logged "NoneType: None" instead of a real
        # traceback. Building the tuple explicitly from the exception
        # object itself (which still carries its own __traceback__)
        # sidesteps that.
        spider.logger.error(
            "Unhandled %s processing %s - logged as dropped, rest of this "
            "response's callback output is lost, crawl continues.",
            type(exception).__name__, response.url,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
        return []
