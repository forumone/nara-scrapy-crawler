"""Project-wide spider middleware - see settings.py's SPIDER_MIDDLEWARES."""


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
    deliberately does not count this reason toward its abort threshold;
    that threshold's message talks about the site/network being
    unreachable, which would misdescribe a parsing bug.

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
