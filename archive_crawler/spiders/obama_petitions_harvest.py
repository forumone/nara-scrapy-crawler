from archive_crawler.spiders.generic_crawl_harvest import GenericCrawlHarvestSpider


class ObamaPetitionsHarvestSpider(GenericCrawlHarvestSpider):
    name = "obama_petitions_harvest"

    # This site's pager links 301 to a canonicalized URL; under the
    # project-wide REDIRECT_ENABLED=False default that redirect is silently
    # dropped instead of followed, truncating pagination after page 1. Safe
    # to re-enable here since this spider only ever yields {'url': ...} - no
    # redirect-detection signal (unlike the content spiders) is being traded
    # away.
    #
    # Output path is automatic, derived from this spider's own site - pass
    # -O <path> on the CLI to override.
    custom_settings = {
        'REDIRECT_ENABLED': True,
        'FEEDS': {
            'data/petitions.obamawhitehouse/petitions.obamawhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'fields': ['url'],
            },
        },
    }

    def __init__(self, url=None, source_site=None, *args, **kwargs):
        super().__init__(
            url=url or 'https://petitions.obamawhitehouse.archives.gov/',
            source_site=source_site or 'petitions.obamawhitehouse',
            *args, **kwargs,
        )
