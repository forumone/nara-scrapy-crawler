from urllib.parse import urlparse

from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import ArchiveSpiderMixin
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin


class OpenSpider(NavHarvesterMixin, ArchiveSpiderMixin, CrawlSpider):
    """Nav-harvest + content-scrape spider for
    open.obamawhitehouse.archives.gov, which has no sitemap. One CrawlSpider
    does both ordinary nav link-following and content extraction
    (_scrape_item) on the same fetched response - no separate harvest pass.

    No listing-fingerprint dedup (LISTING_VIEW_LINK_EXTRACTOR left unset):
    this site is a few hundred pages, with no evidence of the shared-catalog-
    embedded-on-thousands-of-permalinks pattern that mechanism exists for.
    Scope is instead controlled by DEPTH_LIMIT and rules: (see
    exclusion_rules/open.obamawhitehouse.yml for the /field_tags/ facet-trap
    and /node/N/download off-domain-redirect exclusions).
    """

    name = "open_obama_whitehouse"
    allowed_domains = ["open.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'open.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    # DEPTH_LIMIT raised past the mixin's usual 2 - a full unlimited-depth
    # crawl of this site reaches depth 7 at most (confirmed via the prior
    # generic_crawl_harvest-based harvest), so this leaves a comfortable
    # margin.
    #
    # REDIRECT_ENABLED=True overrides the project-wide default: this site's
    # /search pager 301s to a canonicalized URL, and without following
    # redirects that truncates pagination after page 1. The one path that
    # redirected off-domain (/node/N/download) is excluded via rules:
    # (see exclusion_rules/open.obamawhitehouse.yml) rather than relying on
    # offsite filtering, which doesn't apply to an in-flight redirect.
    #
    # FEEDS produces both harvest and content CSVs from this one run, via
    # two named feeds each item_classes-filtered to the matching schema.
    custom_settings = {
        'DEPTH_LIMIT': 30,
        'REDIRECT_ENABLED': True,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEEDS': {
            'data/open.obamawhitehouse/open.obamawhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/open.obamawhitehouse/open.obamawhitehouse.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [ArchiveItem],
                'fields': [
                    'url', 'title', 'teaser_text', 'full_text',
                    'source_site', 'source_type', 'warnings',
                ],
            },
        },
    }

    start_urls = ['https://open.obamawhitehouse.archives.gov/']

    rules = (
        Rule(
            # allow= anchors to the exact hostname; allow_domains alone would
            # also match a subdomain sharing this suffix.
            LinkExtractor(
                allow=r'//open\.obamawhitehouse\.archives\.gov/',
                allow_domains=['open.obamawhitehouse.archives.gov'],
                deny_extensions=(),
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav
        ),
    )

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        # /search and /search/type/* are pure pagination/listing scaffolding
        # - still followed for dataset-link discovery (see parse_nav), just
        # never recorded as a content row. Unlike _parse_generic's other
        # no-body pages (homepage, group pages), a search results page
        # isn't a named thing anyone would search for by title. Logged as
        # an exclusion (not just skipped) so harvest = scrape + exclude
        # still holds - otherwise these URLs would appear in the harvest
        # CSV but in neither the content CSV nor the exclusions CSV.
        if urlparse(response.url).path.startswith('/search'):
            self._log_exclusion(response.url, 'search_listing_page')
            return None
        if 'dataset' in response.url:
            return self._parse_dataset(response)
        return self._parse_generic(response)

    def _parse_dataset(self, response):
        warnings = []
        body = self._extract_text(response, 'div.field-name-body div.field-items')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = response.xpath(
            "normalize-space(//div[contains(@class, 'radix-layouts-content')]//h2[@class='pane-title']/text())"
        ).get(default='').strip()
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        return item

    def _parse_generic(self, response):
        # Non-dataset pages (homepage, group pages, etc.) are navigation/listing
        # pages with no extractable article content, by design - always tagged
        # no_body (never short_body, since body is always empty here, never
        # just short) rather than conditionally checked like the standard
        # paradigm. Return with empty full_text so the page is findable by
        # title in search without polluting full_text with page chrome.
        title = response.xpath('//title/text()').get(default='').strip()
        warnings = ['no_body']
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = ''
        item['teaser_text'] = ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        return item
