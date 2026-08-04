from urllib.parse import urlparse

from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import ArchiveSpiderMixin
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin

# The three exact hostnames this one spider covers - see class docstring for
# why allowed_domains lists these explicitly rather than the bare
# trumpwhitehouse.archives.gov suffix.
MAIN_HOST = 'trumpwhitehouse.archives.gov'
CRISISNEXTDOOR_HOST = 'crisisnextdoor.trumpwhitehouse.archives.gov'
CORONAVIRUS_HOST = 'coronavirus.trumpwhitehouse.archives.gov'


class TrumpWhiteHouseSpider(NavHarvesterMixin, ArchiveSpiderMixin, CrawlSpider):
    """Nav-harvest + content-scrape spider covering three related sites, all
    with no sitemap and all landing in the same "Archived White House
    Websites" search-index tab: the main trumpwhitehouse.archives.gov
    (WordPress) plus its crisisnextdoor and coronavirus subdomains (a
    single-page WordPress microsite and a 2-page static site, respectively).
    One CrawlSpider does both ordinary nav link-following and automatic
    listing pagination-walking via NavHarvesterMixin's fingerprint
    mechanism, and - on that same fetched response - content extraction
    (_scrape_item) via the _maybe_scrape_item hook.

    Folded into one spider rather than three (crisisnextdoor/coronavirus
    were each standalone spiders originally) because the two subdomains are
    trivially small (1-2 pages each) and there is no per-site distinction
    needed downstream: SOURCE_SITE/source_site is a single value across all
    three domains (the URL column already shows which actual subdomain a
    row came from), so there's no output-CSV-routing complexity to justify
    keeping them separate.

    allowed_domains lists the three exact hostnames rather than the bare
    trumpwhitehouse.archives.gov suffix - Scrapy's OffsiteMiddleware treats
    allowed_domains entries as suffix matches, so the bare parent alone
    would silently open the crawl to every OTHER subdomain too (e.g.
    petitions.trumpwhitehouse.archives.gov, which has its own separate
    spider - trump_petitions.py). The Rule's own allow= regex is similarly
    anchored to exactly these three hostnames, not a suffix pattern.

    This is the first WordPress site this crawler has targeted (every prior
    NavHarvesterMixin site is Drupal) - the listing markup below
    (.page-results__wrap / .briefing-statement / .pagination__next) is this
    theme's own, not Drupal's .view/.views-row/.pager-current. It's also
    the first spider to cover more than one hostname - _scrape_item
    dispatches on response hostname since each of the three sites uses a
    completely different template.

    The main site's per-issue facet filters (e.g.
    /briefings-statements/?issue_filter=healthcare) render inside the same
    .page-results__wrap container as the unfiltered listing, each with its
    own populated pager - the fingerprint mechanism treats each filter as its
    own listing (a genuinely different item subset, not a duplicate) and
    walks it once, so no nav_deny/rules entry is needed to keep the crawl
    from re-following every filter link found on every listing page.

    start_urls includes the three known microsites (/ai/, /bebest/, /wgdp/)
    as an explicit belt-and-suspenders measure - they're expected to be
    reachable via ordinary nav-following from the homepage regardless, but
    seeding them directly guarantees coverage even if that linkage is ever
    missing on a given page.
    """

    name = "trumpwhitehouse"
    allowed_domains = [MAIN_HOST, CRISISNEXTDOOR_HOST, CORONAVIRUS_HOST]

    SOURCE_SITE = 'www.trumpwhitehouse'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'

    # .page-results__wrap wraps a listing's facet-filter nav, its item
    # <article>s, AND its .pagination block together (confirmed live on
    # /briefings-statements/) - the WordPress-theme equivalent of Drupal's
    # .view. .pagination__next is only rendered when a next page actually
    # exists (absent on a listing's last page, and on a facet-filtered
    # variant short enough to fit on one page), distinguishing a real
    # paginated listing from a single-page one. Only the main site has this
    # listing template - crisisnextdoor/coronavirus pages simply never match
    # these selectors, so no false-positive risk from sharing them.
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.page-results__wrap',
        allow_domains=[MAIN_HOST],
        deny_extensions=(),
    )
    LISTING_CONTAINER_SELECTOR = '.page-results__wrap'
    LISTING_PAGER_SELECTOR = '.pagination__next'

    # DEPTH_LIMIT raised well past the mixin's usual 2 - /briefings-statements/
    # alone chains 670 pager pages deep (confirmed live), and other listings
    # (news/, issues/, articles/, remarks/, presidential-actions/) may run
    # comparably long. Same DepthMiddleware-shares-one-counter reasoning as
    # obama_whitehouse.py/letsmove.py: without raising this,
    # _walk_listing_pagination's own pager-following would get silently cut
    # off well short of a long listing's true end. Harmless to share across
    # all three hostnames - crisisnextdoor/coronavirus reach depth 0-1 at
    # most regardless of the ceiling.
    custom_settings = {
        'DEPTH_LIMIT': 2500,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEEDS': {
            'data/www.trumpwhitehouse/www.trumpwhitehouse_harvest.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/www.trumpwhitehouse/www.trumpwhitehouse.csv': {
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
        f'https://{MAIN_HOST}/',
        f'https://{MAIN_HOST}/ai/',
        f'https://{MAIN_HOST}/bebest/',
        f'https://{MAIN_HOST}/wgdp/',
        f'https://{CRISISNEXTDOOR_HOST}/',
        f'https://{CORONAVIRUS_HOST}/',
    ]

    rules = (
        Rule(
            # allow= anchors to exactly these three hostnames; allow_domains
            # alone would also match every OTHER trumpwhitehouse subdomain
            # (e.g. petitions.), which has its own separate spider.
            LinkExtractor(
                allow=(
                    r'//trumpwhitehouse\.archives\.gov/',
                    r'//crisisnextdoor\.trumpwhitehouse\.archives\.gov/',
                    r'//coronavirus\.trumpwhitehouse\.archives\.gov/',
                ),
                allow_domains=[MAIN_HOST, CRISISNEXTDOOR_HOST, CORONAVIRUS_HOST],
                deny_extensions=(),
            ),
            callback='parse_nav',
            follow=False,  # links followed manually in parse_nav, only from non-listing pages
        ),
    )

    # The theme's one confirmed listing item template: an
    # article.briefing-statement's own h2.briefing-statement__title link.
    def _listing_pagination_items(self, container):
        return container.css('.briefing-statement__title a::attr(href)').getall()

    def _listing_pagination_next_url(self, container):
        return container.css('.pagination__next::attr(href)').get()

    # Union of all three sites' boilerplate. Each selector only ever matches
    # on its own site's markup (e.g. .nara-disclaimer never appears on the
    # main WordPress site), so sharing the list is harmless rather than
    # gating it per-hostname.
    # .editor__module--left: main site's share-links sidebar + "All News"
    #   back-link modules (editor__module-share/editor__module-all, both
    #   also carry --left). Deliberately NOT the blanket .editor__module -
    #   the site's photo-gallery template (e.g. any /briefings-statements/
    #   photo-*/photos-* page) wraps its own real captions in
    #   .editor__module.editor__module--content, which a blanket strip here
    #   would wipe out along with the sidebar, producing a false no_body
    #   (confirmed live 2026-08-03 on the Cabinet Meeting photos page).
    # .visually-hidden: screen-reader-only labels, confirmed live on both the
    #   main site's microsites (a "heading" reading "Introduction") and
    #   crisisnextdoor (duplicate "WhiteHouse.gov" logo labels).
    # .nara-disclaimer / header nav / footer: coronavirus's NARA archival
    #   banner and site-chrome nav/footer links, not real content.
    EXTRA_STRIP_SELECTORS = (
        '.editor__module--left', '.visually-hidden',
        '.nara-disclaimer', 'header nav', 'footer',
    )

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        host = urlparse(response.url).hostname
        if host == CRISISNEXTDOOR_HOST:
            return self._scrape_crisisnextdoor(response)
        if host == CORONAVIRUS_HOST:
            return self._scrape_coronavirus(response)
        return self._scrape_main(response)

    def _make_item(self, response, title, body, warnings):
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body) if body else ''
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        item['warnings'] = ','.join(warnings)
        return item

    def _scrape_main(self, response):
        warnings = []
        # .microsite__content is the shared wrapper the /ai/ and /wgdp/
        # microsites both use for their actual panel content (each microsite
        # otherwise has its own distinct theme naming -
        # .ai-panel/.wgdp-panel* - confirmed live neither reuses the main
        # site's .page-content__content template). /bebest/ is the one
        # microsite that DOES reuse the main site's ordinary template, so
        # the first selector still covers it.
        body = (self._extract_text(response, '.page-content__content.editor') or
                self._extract_text(response, '.microsite__content'))
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        # _extract_title's generic h1/<title> fallback is deliberately
        # skipped for microsite pages (the shared .microsite wrapper div
        # confirmed live on /ai/ and /wgdp/): each microsite's masthead h1
        # ("Artificial Intelligence for the American People", etc.) and
        # <title> tag are identical across its homepage AND every one of
        # its sub-pages (e.g. /ai/ai-american-values/) - there is no
        # distinguishing per-page title anywhere in the markup. Falling
        # through to _slug_title below gives a more useful,
        # page-distinguishing title than repeating that masthead text on
        # every row.
        title = response.css('.page-header__title').xpath('string(.)').get(default='').strip()
        if not title and not response.css('.microsite'):
            title = self._extract_title(response)
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        return self._make_item(response, title, body, warnings)

    def _scrape_crisisnextdoor(self, response):
        warnings = []
        body = self._extract_text(response, '#main-content')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = response.css('#main-content h1').xpath('string(.)').get(default='').strip()
        if not title:
            title = self._extract_title(response)
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        return self._make_item(response, title, body, warnings)

    def _scrape_coronavirus(self, response):
        warnings = []
        body = self._extract_text(response, 'body')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = response.css('header h1').xpath('string(.)').get(default='').strip()
        if not title:
            title = self._extract_title(response)
        if not title:
            warnings.append('no_title')
            title = self._slug_title(response.url)
        return self._make_item(response, title, body, warnings)
