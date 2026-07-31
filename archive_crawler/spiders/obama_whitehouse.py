import json

from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import ArchiveSpiderMixin, NavHarvesterMixin


class ObamaWhiteHouseSpider(NavHarvesterMixin, ArchiveSpiderMixin, CrawlSpider):
    """Nav-harvest + content-scrape spider for obamawhitehouse.archives.gov,
    which has no sitemap. One CrawlSpider does both ordinary nav
    link-following and automatic listing pagination-walking via
    NavHarvesterMixin's fingerprint mechanism (see that mixin's docstring
    and ARCHITECTURE.md for the full mechanism and its known limitations),
    and - on that same fetched response - this site's content extraction
    (_scrape_item) via the _maybe_scrape_item hook.

    This is what protects against every /photos-and-video/{video,
    photogallery}/* permalink embedding the same sitewide "browse other
    videos/galleries" catalog: the first permalink encountered walks the
    catalog once, and every subsequent permalink's identical item set
    hashes to the same fingerprint and is flagged-and-skipped, never
    re-walked.

    There's no not_in_seed_list-style diagnostic here (outbound links on a
    content page checked against a complete, already-finished harvest URL
    set) - there's no complete prior harvest to check a link against when
    discovery and extraction share one pass; any non-excluded link gets its
    own request queued and eventually visited, by construction.
    """

    name = "obama_whitehouse"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'www.obamawhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    # .view is Drupal Views' own wrapper and reliably encloses both a
    # listing's item rows and its pager/filter controls, confirmed across
    # two distinct templates (teaser-card blog/author listings and the
    # table-based photo/video gallery view both render inside a .view div).
    # .view presence ALONE is not enough, though - ordinary topic/content
    # pages that merely embed a "related videos"/"related blog posts" widget
    # also render inside a .view container with real links, but carry no
    # pager (confirmed: /issues/education/k-12 and the Cairo speech page
    # both do this). LISTING_PAGER_SELECTOR requires an actual populated
    # pager - .pager-current, confirmed present on both real listing
    # templates - before a page counts as a listing at all.
    # deny_extensions=() disables Scrapy's own built-in IGNORED_EXTENSIONS
    # denylist (pdf/doc/zip/jpg/etc.) so our own is_web_url allow-list
    # (archive_crawler/exclusion_rules/<site>.yml) is the sole authority on
    # what counts as a web page.
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['obamawhitehouse.archives.gov'],
        deny_extensions=(),
    )
    LISTING_CONTAINER_SELECTOR = '.view'
    LISTING_PAGER_SELECTOR = '.pager-current'

    # DEPTH_LIMIT raised well past the mixin's usual 20 to comfortably clear
    # the longest known listing pagination chain
    # (briefing-room/statements-and-releases, 1,176 pages). Scrapy's
    # DepthMiddleware counts every response.follow() call toward one shared
    # depth counter regardless of which callback issued it, with no way to
    # reset/exempt a specific chain - so _walk_listing_pagination's own
    # pager-following would otherwise get silently killed well short of a
    # long listing's true end. Safe to raise this high: nav's own ordinary
    # link-following reaches full graph closure at a much shallower depth
    # regardless of the ceiling, and the fingerprint dedup that protects
    # against video/photogallery fan-out is a separate, content-based
    # mechanism independent of DEPTH_LIMIT.
    #
    # FEEDS replaces the old two-spider -O invocation with two named feeds
    # from this one run, item_classes-filtered to the matching schema - the
    # exact fields each of today's separately-produced CSVs already has.
    custom_settings = {
        'DEPTH_LIMIT': 1300,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEEDS': {
            'data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/www.obamawhitehouse/www.obamawhitehouse.csv': {
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

    start_urls = ['https://obamawhitehouse.archives.gov/']

    rules = (
        Rule(
            # allow= anchors to the exact hostname; allow_domains alone would
            # also match subdomains like letsmove.obamawhitehouse.archives.gov.
            LinkExtractor(
                allow=r'//obamawhitehouse\.archives\.gov/',
                allow_domains=['obamawhitehouse.archives.gov'],
                deny_extensions=(),
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav, only from non-listing pages
        ),
    )

    # Three known listing templates: teaser-card (.views-row h2/h3 a, e.g.
    # blog/author pages), table-based gallery (.views-field-title, e.g.
    # photo/video galleries), and person-directory (.views-row
    # .views-field-nid a, e.g. /blog/authors).
    def _listing_pagination_items(self, container):
        links = container.css(
            '.views-row h2 a::attr(href), .views-row h3 a::attr(href)'
        ).getall()
        if not links:
            links = container.css('.views-field-title a::attr(href)').getall()
        if not links:
            links = container.css('.views-row .views-field-nid a::attr(href)').getall()
        return links

    # .pager-current's immediately-following sibling <li> holds the forward
    # link in both templates (a "Next" link in the teaser-card pager, a
    # numbered page link in the gallery pager) - one selector covers both
    # rather than branching on .pager-next (which the gallery template
    # doesn't use at all).
    def _listing_pagination_next_url(self, container):
        return container.css('.pager-current + li a::attr(href)').get()

    @staticmethod
    def _extract_gallery_captions(response):
        """Extract every slideshow caption from a /photos-and-video/
        photogallery/* page.

        The slideshow itself is JS-driven and only ever renders the current
        slide's caption into the visible DOM (#photo-description) - a
        markup-based selector would silently return just one caption instead
        of the gallery's full set. Every caption is also embedded as static
        data in the page's own jQuery.extend(Drupal.settings, {...}) blob
        (Drupal.settings.wh_photog.descriptions), confirmed present and
        parseable on multiple unrelated galleries - no JS execution needed.
        """
        marker = 'jQuery.extend(Drupal.settings,'
        start = response.text.find(marker)
        if start == -1:
            return ''
        brace_start = response.text.find('{', start)
        if brace_start == -1:
            return ''
        try:
            settings, _ = json.JSONDecoder().raw_decode(response.text, brace_start)
        except json.JSONDecodeError:
            return ''
        descriptions = settings.get('wh_photog', {}).get('descriptions') or []
        return ' '.join(d.strip() for d in descriptions if d and d.strip())

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        warnings = []
        # _extract_first_substantial, not _extract_text: a Drupal "Panels"
        # landing page (e.g. /sotu) renders 100+ unrelated .field-item panes
        # in document order, and the first one can be an unrelated
        # video-embed-fallback link rather than real content - scan for the
        # first pane whose cleaned text actually clears the short_body
        # threshold instead of blindly taking the first match (D-009).
        body = (self._extract_first_substantial(response, '.field-items .field-item') or
                self._extract_text(response, '.longpage-sections') or
                self._extract_text(response, '#content') or
                self._extract_text(response, '#video-info .caption') or
                self._extract_gallery_captions(response))
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = self._extract_title(response)
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
