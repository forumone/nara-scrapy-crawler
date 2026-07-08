"""
Generic harvest spider — phase 1 of the two-phase crawl workflow.

Crawls a site from a single entry-point URL, follows all internal links,
and writes a URL-per-row CSV. That CSV is the input to generic_crawl (phase 2).

Pagination links (?page=, /page/) are followed to reach listing pages beyond
the first, but not recorded as harvested content themselves — only the
content links discovered on them are. Every followed link also has its query
string reduced to just the pagination param (if any); this relies on
Scrapy's default duplicate-request filter to collapse facet/sort/tracking
query-string variants of the same page (e.g. Drupal/CKAN-style faceted
search) down to a single crawl instead of one per decoration. It does not,
however, stop
distinct facet *paths* (e.g. chained /field_tags/X/field_tags/Y/ segments)
from each being crawled once each — that's a structural, site-specific
pattern; block it per-run with urls_to_skip.

See HARVESTING.md for guidance on when to use this vs. the split nav+list
harvester pattern (sites where content is reachable ONLY through pagination,
with no other navigation path to it).

Usage
-----
Basic crawl of an entire domain:

    scrapy crawl generic_crawl_harvest \
        -a url=https://example.archives.gov/ \
        -o data/example_harvest.csv

Excluding paths that generate noise (comma-separated regex fragments):

    scrapy crawl generic_crawl_harvest \
        -a url=https://example.archives.gov/ \
        -a urls_to_skip='/print/,/user/,/node/\\d' \
        -o data/example_harvest.csv

Arguments
---------
url          Required. The root URL to start crawling. The spider confines
             itself to the domain extracted from this URL.
urls_to_skip Optional. Comma-separated list of regex fragments passed as
             deny patterns to the LinkExtractor. Useful for excluding
             Drupal print views, user pages, raw node paths, faceted-search
             paths, etc.

Customising for a new site
--------------------------
If the generic deny rules aren't sufficient, subclass this spider and override
rules with a site-specific LinkExtractor. The harvest output format (a single
'url' column) must stay the same so generic_crawl can consume it unchanged.
"""
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from scrapy.linkextractors import IGNORED_EXTENSIONS, LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

# Scrapy's default IGNORED_EXTENSIONS skips images/office docs/archives/media
# but not raw data-dump formats, which data-catalog-style sites (e.g. Drupal
# or CKAN open-data catalogs) link to directly. Downloading one of these as
# if it were a page can pull many MB into memory per response for no benefit
# — they have no title/body for parse_url to extract anyway.
DENY_EXTENSIONS = [*IGNORED_EXTENSIONS, 'csv', 'json', 'xml', 'tsv', 'txt']

PAGINATION_PATTERNS = (r'\?page=', r'/page/')

# Query params preserved when normalizing a link before it's scheduled; every
# other param is stripped. See module docstring for why.
ALLOWED_QUERY_PARAMS = {'page'}


def _strip_noise_query_params(links):
    for link in links:
        parts = urlsplit(link.url)
        kept = [(k, v) for k, v in parse_qsl(parts.query) if k in ALLOWED_QUERY_PARAMS]
        link.url = urlunsplit(parts._replace(query=urlencode(kept)))
    return links


class GenericCrawlHarvestSpider(CrawlSpider):
    name = "generic_crawl_harvest"

    def __init__(self, url=None, urls_to_skip=None, *args, **kwargs):
        if not url:
            raise ValueError("No 'url' argument provided.")

        self.start_urls = [url]
        self.allowed_domains = [urlparse(url).netloc]

        deny_list = []
        if urls_to_skip:
            deny_list = [s.strip() for s in urls_to_skip.split(',') if s.strip()]

        self.rules = (
            # Pagination: follow to reach listing pages beyond the first, but
            # don't record the listing page itself as harvested content.
            Rule(
                LinkExtractor(
                    allow=PAGINATION_PATTERNS,
                    deny_extensions=DENY_EXTENSIONS,
                    unique=True,
                ),
                process_links=_strip_noise_query_params,
                follow=True,
            ),
            # Everything else: follow and record as harvested content.
            Rule(
                LinkExtractor(
                    deny=(*PAGINATION_PATTERNS, *deny_list),
                    deny_extensions=DENY_EXTENSIONS,
                    unique=True,
                ),
                process_links=_strip_noise_query_params,
                callback='parse_url',
                follow=True,
            ),
        )

        super().__init__(*args, **kwargs)

    def parse_url(self, response):
        yield {'url': response.url}
