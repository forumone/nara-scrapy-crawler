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
however, stop distinct facet *paths* (e.g. chained /field_tags/X/field_tags/Y/
segments) from each being crawled once each - that's a structural,
site-specific pattern; block it via a rules_file's rules: patterns (see
Arguments below).

See HARVESTING.md for guidance on when to use this vs. the split nav+list
harvester pattern (sites where content is reachable ONLY through pagination,
with no other navigation path to it).

Usage
-----
Basic crawl of an entire domain:

    scrapy crawl generic_crawl_harvest \
        -a url=https://example.archives.gov/ \
        -o data/example_harvest.csv

Excluding paths that generate noise, and/or targeting a specific site's
committed rules file:

    scrapy crawl generic_crawl_harvest \
        -a url=https://example.archives.gov/ \
        -a source_site=example \
        -a rules_file=data/example/one_off_extra_denies.yml \
        -a rules_mode=append \
        -o data/example_harvest.csv

Arguments
---------
url          Required. The root URL to start crawling. The spider confines
             itself to the domain extracted from this URL.
source_site  Optional. Loads archive_crawler/exclusion_rules/<source_site>.yml
             instead of this spider's own generic_crawl_harvest.yml default.
             Use when a site accumulates its own reusable rules file.
rules_file   Optional. Path to a YAML file overlaid on whichever of the above
             gets loaded - -a rules_mode=append (default) unions its rules/
             pagination/query_params_allow with the base file's, or
             'replace' to use rules_file's instead. Neither the base file nor
             rules_file is written to; this is a runtime-only override.

Customising for a new site
--------------------------
If the generic deny rules aren't sufficient, subclass this spider and override
rules with a site-specific LinkExtractor. The harvest output format (a single
'url' column) must stay the same so generic_crawl can consume it unchanged.
"""
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from scrapy.linkextractors import IGNORED_EXTENSIONS, LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler import exclusion_rules

# Baseline for a source_site whose exclusion_rules extensions mode is
# 'allow' (the norm for any known site's own committed YAML) - an allow-list
# isn't directly usable as deny_extensions, so this is what actually gets
# applied at the LinkExtractor level for those sites. Scrapy's own
# IGNORED_EXTENSIONS (images/office docs/archives/media) plus data-dump
# formats (csv/json/xml/tsv/txt), since data-catalog-style sites (Drupal or
# CKAN open-data catalogs) commonly link to raw data files directly, and
# downloading one as if it were a page pulls potentially many MB into
# memory for no benefit - no title/body for parse_url to extract anyway,
# and some formats (JSON in particular) crash Scrapy's own HTML-assuming
# link-extraction outright rather than just wasting bandwidth.
_BASE_DENY_EXTENSIONS = [*IGNORED_EXTENSIONS, 'csv', 'json', 'xml', 'tsv', 'txt']


def _strip_noise_query_params(links, allowed_query_params):
    for link in links:
        parts = urlsplit(link.url)
        kept = [(k, v) for k, v in parse_qsl(parts.query) if k in allowed_query_params]
        link.url = urlunsplit(parts._replace(query=urlencode(kept)))
    return links


class GenericCrawlHarvestSpider(CrawlSpider):
    name = "generic_crawl_harvest"

    def __init__(self, url=None, source_site=None, rules_file=None,
                 rules_mode='append', *args, **kwargs):
        if not url:
            raise ValueError("No 'url' argument provided.")

        self.start_urls = [url]
        self.allowed_domains = [urlparse(url).netloc]

        rules = exclusion_rules.load_rules(source_site or self.name, rules_file, rules_mode)
        deny_extensions = rules.extensions.get('values', []) \
            if rules.extensions.get('mode') == 'deny' else _BASE_DENY_EXTENSIONS
        pagination_patterns = exclusion_rules.pagination_patterns(rules)
        allowed_query_params = exclusion_rules.allowed_query_params(rules)
        process_links = lambda links: _strip_noise_query_params(links, allowed_query_params)

        self.rules = (
            # Pagination: follow to reach listing pages beyond the first, but
            # don't record the listing page itself as harvested content.
            Rule(
                LinkExtractor(
                    allow=pagination_patterns,
                    deny_extensions=deny_extensions,
                    unique=True,
                ),
                process_links=process_links,
                follow=True,
            ),
            # Everything else: follow and record as harvested content.
            Rule(
                LinkExtractor(
                    deny=pagination_patterns,
                    deny_extensions=deny_extensions,
                    unique=True,
                ),
                process_links=process_links,
                callback='parse_url',
                follow=True,
            ),
        )

        super().__init__(*args, **kwargs)

    def parse_url(self, response):
        yield {'url': response.url}
