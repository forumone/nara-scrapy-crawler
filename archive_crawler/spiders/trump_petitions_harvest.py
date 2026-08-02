from archive_crawler.spiders.generic_crawl_harvest import GenericCrawlHarvestSpider


class TrumpPetitionsHarvestSpider(GenericCrawlHarvestSpider):
    name = "trump_petitions_harvest"

    # This site's pager links also 301 to a canonicalized URL, silently
    # truncating pagination under the project-wide REDIRECT_ENABLED=False
    # default.
    #
    # Output path is automatic, derived from this spider's own site - pass
    # -O <path> on the CLI to override.
    custom_settings = {
        'REDIRECT_ENABLED': True,
        'FEEDS': {
            'data/petitions.trumpwhitehouse/petitions.trumpwhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'fields': ['url'],
            },
        },
    }

    def __init__(self, url=None, source_site=None, *args, **kwargs):
        super().__init__(
            url=url or 'https://petitions.trumpwhitehouse.archives.gov/',
            source_site=source_site or 'petitions.trumpwhitehouse',
            *args, **kwargs,
        )
