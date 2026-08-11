"""Site discovery for scrape_index_pipeline.

Enumerates every content spider registered under archive_crawler.spiders.
Every in-scope site is invocable the same way (`scrapy crawl <name> -O
data/<site>/<site>.csv`) - no sitemap-based/link-crawler distinction needed
"""
import os
from collections import namedtuple

from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader

# One-off exploratory tools (not fixed-site content spiders) and sites
# out of indexing scope
_EXCLUDED_SPIDER_NAMES = frozenset({
    'generic_crawl', 'generic_crawl_harvest', 'sitemap_harvest',
    'obama_petitions', 'trump_petitions',
})

SiteInfo = namedtuple('SiteInfo', ['source_site', 'spider_name', 'csv_path'])


class UnknownSiteError(ValueError):
    pass


def _settings():
    settings = Settings()
    settings.setmodule('archive_crawler.settings')
    return settings


def list_sites():
    """Return {source_site: SiteInfo}, one entry per content spider."""
    loader = SpiderLoader.from_settings(_settings())
    sites = {}
    for spider_name in loader.list():
        if spider_name in _EXCLUDED_SPIDER_NAMES:
            continue
        spider_cls = loader.load(spider_name)
        source_site = getattr(spider_cls, 'SOURCE_SITE', None)
        if not source_site:
            continue
        sites[source_site] = SiteInfo(
            source_site=source_site,
            spider_name=spider_name,
            csv_path=os.path.join('data', source_site, f'{source_site}.csv'),
        )
    return sites


def resolve(site_arg):
    """Look up a SiteInfo by either its spider name (e.g. 'bidenwhitehouse')
    or its source_site (e.g. 'www.bidenwhitehouse') - the two differ for
    several sites, and an operator typing a CLI command is more likely to
    know the spider name than the SOURCE_SITE value. Raises
    UnknownSiteError if neither matches."""
    sites = list_sites()
    if site_arg in sites:
        return sites[site_arg]
    for info in sites.values():
        if info.spider_name == site_arg:
            return info
    known = ', '.join(sorted(info.spider_name for info in sites.values()))
    raise UnknownSiteError(f"{site_arg!r} is not a known site (spider name or source_site). Known spiders: {known}")
