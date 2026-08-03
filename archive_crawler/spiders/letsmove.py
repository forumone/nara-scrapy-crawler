from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import ArchiveSpiderMixin
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin


class LetsMoveSpider(NavHarvesterMixin, ArchiveSpiderMixin, CrawlSpider):
    """Nav-harvest + content-scrape spider for
    letsmove.obamawhitehouse.archives.gov. One CrawlSpider walks every page
    exactly once: parse_nav (NavHarvesterMixin) discovers/flags listings and
    auto-walks pagination, and - on that same fetched response, no second
    request - also runs this site's content extraction (_scrape_item,
    ArchiveSpiderMixin's role) via the _maybe_scrape_item hook.

    Much smaller/lower-risk than the Obama WH site: one main listing section
    (/blog/), no video/photogallery-style shared-catalog concern. Individual
    blog posts also embed a "recent posts" widget sharing the same view id
    and pager-token scheme as /blog/'s own listing - if its item set is
    identical across posts, the fingerprint mechanism collapses it the same
    way as any other shared catalog; if it varies per post, each gets walked
    once, which is harmless at this site's scale either way.
    """

    name = "letsmove"
    allowed_domains = ["letsmove.obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'letsmove.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    # .view wraps both the blog listing's item rows and its <ul class="pager">
    # block (confirmed nested together on the live site, single .view
    # occurrence on the page - no related-content false-positive risk
    # observed). .pager is the signal a real pager is present (Drupal only
    # renders this block for a genuinely multi-page view), distinguishing a
    # real listing from any content page that might embed a single-item
    # .view widget with no pagination.
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['letsmove.obamawhitehouse.archives.gov'],
        deny_extensions=(),
    )
    LISTING_CONTAINER_SELECTOR = '.view'
    LISTING_PAGER_SELECTOR = '.pager'

    # DEPTH_LIMIT raised to comfortably clear the /blog/ listing's full
    # pagination chain (this site's pager URLs are opaque hashed tokens, not
    # sequential page numbers, so the chain length has to be walked rather
    # than inferred from the markup). Same DepthMiddleware-shares-one-counter
    # reasoning as obama_whitehouse.py: without raising this,
    # _walk_listing_pagination's own pager-following would get silently cut
    # off well short of the listing's true end.
    #
    # FEEDS gives two named feeds from this one run, item_classes-filtered
    # to the matching schema - a harvest CSV and a content CSV.
    custom_settings = {
        'DEPTH_LIMIT': 200,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEEDS': {
            'data/letsmove.obamawhitehouse/letsmove.obamawhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/letsmove.obamawhitehouse/letsmove.obamawhitehouse.csv': {
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

    start_urls = [
        "https://letsmove.obamawhitehouse.archives.gov/",
    ]

    rules = (
        Rule(
            LinkExtractor(deny_extensions=()),
            callback='parse_nav',
            follow=False,
        ),
    )

    def _listing_pagination_items(self, container):
        return container.css('.views-row .views-field-title a::attr(href)').getall()

    def _listing_pagination_next_url(self, container):
        return container.css('.pager-next a::attr(href)').get()

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        warnings = []
        body = self._extract_text(response, '#maincontent .node .content')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = response.css('#maincontent h1').xpath('string(.)').get(default='').strip()
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
