from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

from archive_crawler import exclusion_rules
from archive_crawler.spiders.base import NavHarvesterMixin


class ObamaWhiteHouseHarvestSpider(NavHarvesterMixin, CrawlSpider):
    """Unified nav+listing discovery pass, replacing the separate
    obama_whitehouse_harvest_nav/_list spiders and merge_harvest.py's
    reconciliation step for this site. Still URL-discovery only (no content
    extraction) - the content spider (obama_whitehouse.py) remains a
    separate, later, explicitly-gated stage.

    Why unify: nav's own ordinary link-following (DEPTH_LIMIT=20, BFS) was
    already proven to reach full graph closure from the homepage alone
    (zero depth-exceeded ignores in prior runs) - the only thing it
    deliberately never does is follow into a flagged listing's own .view
    container (item rows + pager), to avoid fanning out into a listing's
    full item/pagination range during ordinary graph traversal. That
    container-skip is the actual load-bearing protection this whole split
    ever needed, not depth limitation, which nav alone already handles
    (raising DEPTH_LIMIT from 2 to 20 already made a large curated
    start_urls list unnecessary for nav's own coverage). Running two
    separate spider processes - nav discovering + flagging listings,
    listing separately walking a manually-promoted seed list, then
    merge_harvest.py reconciling the two output files - added a slow
    human-curation step between discovery and walking, and forced the
    content spider to grow its own belated not_in_seed_list check to catch
    whatever the two-pass model missed. Folding listing's pagination-walk in
    as a branch of this same spider - dispatched only for a still-curated,
    still human-reviewed seed list (LISTING_SEEDS below), never
    automatically for every flagged listing nav happens to discover - keeps
    the exact same fan-out protection while removing the extra
    process/merge step.
    """

    name = "obama_whitehouse_harvest"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    SOURCE_SITE = 'www.obamawhitehouse'
    # Distinct from the old 'nav-exclusions'/'listing-exclusions' pair (both
    # remain on disk as historical reference, not overwritten) - this is one
    # unified exclusion log for the merged spider.
    EXCLUSIONS_FILE_SUFFIX = 'harvest-exclusions'

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
    LISTING_PAGER_SELECTOR = '.pager-current'

    # DEPTH_LIMIT raised well past the mixin's usual 20 to comfortably clear
    # the longest known curated-listing pagination chain
    # (briefing-room/statements-and-releases, 1,176 pages). Scrapy's
    # DepthMiddleware counts every response.follow() call toward one shared
    # depth counter regardless of which callback issued it - confirmed by
    # reading DepthMiddleware._filter directly, it computes
    # request.meta['depth'] from the CURRENT response's own depth with no
    # way to reset/exempt a specific chain - so _walk_listing_pagination's
    # own pager-following would otherwise get silently killed around page 20
    # instead of reaching each section's true end.
    #
    # Safe to raise this high: nav's own ordinary link-following is
    # independently proven to reach full graph closure by depth 19
    # regardless of the ceiling (zero depth-exceeded ignores at
    # DEPTH_LIMIT=20 in prior runs, i.e. nothing reachable via ordinary
    # links sits anywhere near this new ceiling anyway). The
    # video/photogallery fan-out protection (LISTING_VIEW_LINK_EXTRACTOR's
    # container-skip) is a separate, content-based mechanism independent of
    # DEPTH_LIMIT, so raising this ceiling does not reopen that risk for any
    # NON-curated listing nav happens to wander into during ordinary
    # traversal - those still only ever get flagged is_listing=True and
    # skipped, never pagination-walked.
    #
    # FEED_EXPORT_FIELDS declared explicitly so the CSV header doesn't
    # depend on whichever item happens to export first - this spider yields
    # both nav-flavored dicts (url+is_listing+depth) and bare listing-item
    # dicts (url only) in the same run, and Scrapy's CsvItemExporter
    # otherwise infers fields_to_export from the first item's own keys
    # alone (a real race under concurrent requests, confirmed by reading
    # CsvItemExporter._write_headers_and_set_fields_to_export directly).
    custom_settings = {
        'DEPTH_LIMIT': 1300,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        'FEED_EXPORT_FIELDS': ['url', 'is_listing', 'depth'],
    }

    # Curated listing seeds whose pagination gets walked directly, in this
    # same spider run, rather than merely flagged is_listing=True and
    # skipped like an ordinarily-discovered listing would be. Ported
    # unchanged from the old obama_whitehouse_harvest_list.py's start_urls -
    # still a human-reviewed, deliberately curated list, NOT auto-walked for
    # every flagged listing nav happens to discover.
    #
    # Only one seed each for the video and photogallery templates,
    # deliberately - every /photos-and-video/video/* permalink and every
    # /photos-and-video/photogallery/* permalink embeds the *same* sitewide
    # "browse other videos/galleries" catalog (confirmed via diffing item
    # lists across multiple unrelated permalinks - byte identical, ~5,920
    # videos across 740 pages for the video template alone). Seeding more
    # than one of each just re-walks that identical catalog from a
    # different entry point for no new content. Do not add more of either
    # template back without first confirming (via a fresh diff) that it's a
    # genuinely distinct, non-shared catalog - this is precisely the
    # mechanism that would otherwise produce millions of redundant
    # pagination page visits (see NAD2-472 project memory's
    # "pagination-widget hypothesis" for the full arithmetic).
    LISTING_SEEDS = [
        "https://obamawhitehouse.archives.gov/briefing-room/speeches-and-remarks",
        "https://obamawhitehouse.archives.gov/briefing-room/press-briefings",
        "https://obamawhitehouse.archives.gov/briefing-room/statements-and-releases",
        "https://obamawhitehouse.archives.gov/briefing-room/presidential-actions",
        "https://obamawhitehouse.archives.gov/briefing-room/weekly-address",
        "https://obamawhitehouse.archives.gov/blog",
        # Discovered via the nav harvester's is_listing=True flagging
        # (2026-07-25 runs), reviewed and confirmed as real listings.
        "https://obamawhitehouse.archives.gov/administration/eop/cea/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/ceq/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/ceq/press_releases",
        "https://obamawhitehouse.archives.gov/administration/eop/cwg/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/iga/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/ofbnp/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/ope/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/ostp/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/ostp/pressroom",
        "https://obamawhitehouse.archives.gov/administration/eop/oua/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/oua/press",
        "https://obamawhitehouse.archives.gov/administration/eop/sicp/blog",
        "https://obamawhitehouse.archives.gov/blog/author/Shaun-Donovan",
        "https://obamawhitehouse.archives.gov/blog/author/adam-garber",
        "https://obamawhitehouse.archives.gov/blog/author/ali-zaidi",
        "https://obamawhitehouse.archives.gov/blog/author/amy-dudley",
        "https://obamawhitehouse.archives.gov/blog/author/aneesh-chopra",
        "https://obamawhitehouse.archives.gov/blog/author/ben-rhodes",
        "https://obamawhitehouse.archives.gov/blog/author/brian-deese",
        "https://obamawhitehouse.archives.gov/blog/author/brian-levine",
        "https://obamawhitehouse.archives.gov/blog/author/broderick-johnson",
        "https://obamawhitehouse.archives.gov/blog/author/carrie-bettinger-lopez",
        "https://obamawhitehouse.archives.gov/blog/author/cecilia-mu%C3%B1oz",
        "https://obamawhitehouse.archives.gov/blog/author/charlie-anderson",
        "https://obamawhitehouse.archives.gov/blog/author/colleen-curtis",
        "https://obamawhitehouse.archives.gov/blog/author/craig-fugate",
        "https://obamawhitehouse.archives.gov/blog/author/dan-utech",
        "https://obamawhitehouse.archives.gov/blog/author/danny-werfel",
        "https://obamawhitehouse.archives.gov/blog/author/david-vandivier",
        "https://obamawhitehouse.archives.gov/blog/author/david-wilkinson",
        "https://obamawhitehouse.archives.gov/blog/author/derek-douglas",
        "https://obamawhitehouse.archives.gov/blog/author/dj-patil",
        "https://obamawhitehouse.archives.gov/blog/author/doug-rand",
        "https://obamawhitehouse.archives.gov/blog/author/dr-jill-biden",
        "https://obamawhitehouse.archives.gov/blog/author/elizabeth-alexander",
        "https://obamawhitehouse.archives.gov/blog/author/eric-waldo",
        "https://obamawhitehouse.archives.gov/blog/author/felicia-escobar",
        "https://obamawhitehouse.archives.gov/blog/author/first-lady-michelle-obama",
        "https://obamawhitehouse.archives.gov/blog/author/gayle-smith",
        "https://obamawhitehouse.archives.gov/blog/author/gina-mccarthy",
        "https://obamawhitehouse.archives.gov/blog/author/grant-t-harris",
        "https://obamawhitehouse.archives.gov/blog/author/greg-nelson",
        "https://obamawhitehouse.archives.gov/blog/author/hope-hall",
        "https://obamawhitehouse.archives.gov/blog/author/howard-schmidt",
        "https://obamawhitehouse.archives.gov/blog/author/jack-lew",
        "https://obamawhitehouse.archives.gov/blog/author/jared-bernstein",
        "https://obamawhitehouse.archives.gov/blog/author/jason-furman",
        "https://obamawhitehouse.archives.gov/blog/author/jeffrey-zients",
        "https://obamawhitehouse.archives.gov/blog/author/jennifer-erickson",
        "https://obamawhitehouse.archives.gov/blog/author/jennifer-palmieri",
        "https://obamawhitehouse.archives.gov/blog/author/jerry-abramson",
        "https://obamawhitehouse.archives.gov/blog/author/jesse-lee",
        "https://obamawhitehouse.archives.gov/blog/author/joshua-miller",
        "https://obamawhitehouse.archives.gov/blog/author/julie-chavez-rodriguez",
        "https://obamawhitehouse.archives.gov/blog/author/kori-schulman",
        "https://obamawhitehouse.archives.gov/blog/author/kristin-lee",
        "https://obamawhitehouse.archives.gov/blog/author/kyle-lierman",
        "https://obamawhitehouse.archives.gov/blog/author/laura-miller",
        "https://obamawhitehouse.archives.gov/blog/author/lauren-kelly",
        "https://obamawhitehouse.archives.gov/blog/author/lindsay-holst",
        "https://obamawhitehouse.archives.gov/blog/author/lisa-o-monaco",
        "https://obamawhitehouse.archives.gov/blog/author/liz-oxhorn",
        "https://obamawhitehouse.archives.gov/blog/author/lloyd-whitman",
        "https://obamawhitehouse.archives.gov/blog/author/macon-phillips",
        "https://obamawhitehouse.archives.gov/blog/author/matt-compton",
        "https://obamawhitehouse.archives.gov/blog/author/maureen-tracey-mooney",
        "https://obamawhitehouse.archives.gov/blog/author/megan-slack",
        "https://obamawhitehouse.archives.gov/blog/author/megan-smith",
        "https://obamawhitehouse.archives.gov/blog/author/michael-botticelli",
        "https://obamawhitehouse.archives.gov/blog/author/monique-dorsainvil",
        "https://obamawhitehouse.archives.gov/blog/author/pete-souza",
        "https://obamawhitehouse.archives.gov/blog/author/president-barack-obama",
        "https://obamawhitehouse.archives.gov/blog/author/r-david-edelman",
        "https://obamawhitehouse.archives.gov/blog/author/rachel-kopilow",
        "https://obamawhitehouse.archives.gov/blog/author/rick-weiss",
        "https://obamawhitehouse.archives.gov/blog/author/roberto-j-rodr%C3%ADguez",
        "https://obamawhitehouse.archives.gov/blog/author/samantha-power",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-anthony-foxx",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-arne-duncan",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-ernest-moniz",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-penny-pritzker",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-ray-lahood",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-steven-chu",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-sylvia-mathews-burwell",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-thomas-e-perez",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-tom-vilsack",
        "https://obamawhitehouse.archives.gov/blog/author/simone-leiro",
        "https://obamawhitehouse.archives.gov/blog/author/steve-vanroekel",
        "https://obamawhitehouse.archives.gov/blog/author/terrell-mcsweeny",
        "https://obamawhitehouse.archives.gov/blog/author/thomas-kalil",
        "https://obamawhitehouse.archives.gov/blog/author/tobin-marcus",
        "https://obamawhitehouse.archives.gov/blog/author/todd-park",
        "https://obamawhitehouse.archives.gov/blog/author/valerie-jarrett",
        "https://obamawhitehouse.archives.gov/blog/author/victoria-espinel",
        "https://obamawhitehouse.archives.gov/champions/blog",
        "https://obamawhitehouse.archives.gov/economy/business/startup-america",
        "https://obamawhitehouse.archives.gov/economy/business/startup-america/commitments",
        "https://obamawhitehouse.archives.gov/economy/business/startup-america/contact",
        "https://obamawhitehouse.archives.gov/economy/business/startup-america/progress-report",
        "https://obamawhitehouse.archives.gov/economy/jobs/news",
        "https://obamawhitehouse.archives.gov/economy/jobsact",
        "https://obamawhitehouse.archives.gov/goodgovernment/news",
        "https://obamawhitehouse.archives.gov/issues/education/k-12/connected",
        "https://obamawhitehouse.archives.gov/issues/education/k-12/race-to-the-top",
        "https://obamawhitehouse.archives.gov/jobsact/read-the-bill",
        "https://obamawhitehouse.archives.gov/joiningforces/blog",
        "https://obamawhitehouse.archives.gov/omb/blog",
        "https://obamawhitehouse.archives.gov/ondcp/blog",
        "https://obamawhitehouse.archives.gov/open/blog",
        "https://obamawhitehouse.archives.gov/photos-and-video/photogallery/archives-first-families-celebrate-holidays-white-house",
        "https://obamawhitehouse.archives.gov/photos-and-video/video/2009/12/22/gingerbread-white-house",
        "https://obamawhitehouse.archives.gov/recovery/blog",
        "https://obamawhitehouse.archives.gov/strongmiddleclass/blog",
        "https://obamawhitehouse.archives.gov/video/President-Obama-Speaks-to-the-Muslim-World-from-Cairo-Egypt",
        "https://obamawhitehouse.archives.gov/video/President-Obama-on-Urban-Policy",
        # Discovered via the nav harvester run 5 (DEPTH_LIMIT=12, tightened
        # is_listing check), reviewed and confirmed as real listings.
        # Excluded from promotion: 4 congress.gov-linked legislation
        # listings (external content, not indexable via this spider - see
        # NAD2-472 project memory for the full 4-listing/pending-legislation
        # writeup), 3 redundant old /video/ URL aliases (identical items to
        # an already-covered gallery), /blog/authors (0 items under current
        # selectors - different markup, not yet walkable), and one redundant
        # pagination artifact of an already-listed root.
        "https://obamawhitehouse.archives.gov/1is2many/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/aapi/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/dpc/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/nec/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/nsc/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/nsc/press",
        "https://obamawhitehouse.archives.gov/administration/eop/oceans/whats-new",
        "https://obamawhitehouse.archives.gov/administration/eop/rural-council/blog",
        "https://obamawhitehouse.archives.gov/administration/eop/rural-council/policy-initiatives",
        "https://obamawhitehouse.archives.gov/administration/eop/rural-council/press",
        "https://obamawhitehouse.archives.gov/administration/eop/rural-council/rural-blog-posts",
        "https://obamawhitehouse.archives.gov/africanamericans/blog",
        "https://obamawhitehouse.archives.gov/africanamericans/press",
        "https://obamawhitehouse.archives.gov/arabamericans/blog",
        "https://obamawhitehouse.archives.gov/blog/author/alan-krueger",
        "https://obamawhitehouse.archives.gov/blog/author/alejandra-campoverdi",
        "https://obamawhitehouse.archives.gov/blog/author/alex-wall",
        "https://obamawhitehouse.archives.gov/blog/author/amanda-stone",
        "https://obamawhitehouse.archives.gov/blog/author/ambassador-ron-kirk",
        "https://obamawhitehouse.archives.gov/blog/author/ambassador-susan-rice",
        "https://obamawhitehouse.archives.gov/blog/author/amy-lansky",
        "https://obamawhitehouse.archives.gov/blog/author/ari-matusiak",
        "https://obamawhitehouse.archives.gov/blog/author/ashleigh-axios",
        "https://obamawhitehouse.archives.gov/blog/author/austan-goolsbee",
        "https://obamawhitehouse.archives.gov/blog/author/betsey-stevenson",
        "https://obamawhitehouse.archives.gov/blog/author/brad-cooper",
        "https://obamawhitehouse.archives.gov/blog/author/cameron-brenchley",
        "https://obamawhitehouse.archives.gov/blog/author/cass-sunstein",
        "https://obamawhitehouse.archives.gov/blog/author/dan-pfeiffer",
        "https://obamawhitehouse.archives.gov/blog/author/david-hudson",
        "https://obamawhitehouse.archives.gov/blog/author/dr-tamara-dickinson",
        "https://obamawhitehouse.archives.gov/blog/author/elizabeth-warren",
        "https://obamawhitehouse.archives.gov/blog/author/erin-lindsay",
        "https://obamawhitehouse.archives.gov/blog/author/ezra-mechaber",
        "https://obamawhitehouse.archives.gov/blog/author/gautam-raghavan",
        "https://obamawhitehouse.archives.gov/blog/author/gene-sperling",
        "https://obamawhitehouse.archives.gov/blog/author/heather-zichal",
        "https://obamawhitehouse.archives.gov/blog/author/jen-psaki",
        "https://obamawhitehouse.archives.gov/blog/author/jenna-brayton",
        "https://obamawhitehouse.archives.gov/blog/author/john-podesta",
        "https://obamawhitehouse.archives.gov/blog/author/jon-carson",
        "https://obamawhitehouse.archives.gov/blog/author/jonathan-greenblatt",
        "https://obamawhitehouse.archives.gov/blog/author/josh-earnest",
        "https://obamawhitehouse.archives.gov/blog/author/joshua-dubois",
        "https://obamawhitehouse.archives.gov/blog/author/kalpen-modi",
        "https://obamawhitehouse.archives.gov/blog/author/karen-mills",
        "https://obamawhitehouse.archives.gov/blog/author/kasie-coccaro",
        "https://obamawhitehouse.archives.gov/blog/author/katelyn-sabochik",
        "https://obamawhitehouse.archives.gov/blog/author/katherine-vargas",
        "https://obamawhitehouse.archives.gov/blog/author/ken-meyer",
        "https://obamawhitehouse.archives.gov/blog/author/ken-salazar",
        "https://obamawhitehouse.archives.gov/blog/author/kumar-garg",
        "https://obamawhitehouse.archives.gov/blog/author/luis-miranda",
        "https://obamawhitehouse.archives.gov/blog/author/lynn-rosenthal",
        "https://obamawhitehouse.archives.gov/blog/author/matt-flavin",
        "https://obamawhitehouse.archives.gov/blog/author/matt-nosanchuk",
        "https://obamawhitehouse.archives.gov/blog/author/max-sgro",
        "https://obamawhitehouse.archives.gov/blog/author/melanie-garunay",
        "https://obamawhitehouse.archives.gov/blog/author/melody-barnes",
        "https://obamawhitehouse.archives.gov/blog/author/michael-daniel",
        "https://obamawhitehouse.archives.gov/blog/author/nancy-ann-deparle",
        "https://obamawhitehouse.archives.gov/blog/author/nancy-sutley",
        "https://obamawhitehouse.archives.gov/blog/author/nathaniel-lubin",
        "https://obamawhitehouse.archives.gov/blog/author/nikki-sutton",
        "https://obamawhitehouse.archives.gov/blog/author/peter-orszag",
        "https://obamawhitehouse.archives.gov/blog/author/peter-welsch",
        "https://obamawhitehouse.archives.gov/blog/author/ronnie-cho",
        "https://obamawhitehouse.archives.gov/blog/author/sam-kass",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-hilda-solis",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-juli%C3%A1n-castro",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-kathleen-sebelius",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-sally-jewell",
        "https://obamawhitehouse.archives.gov/blog/author/stephanie-cutter",
        "https://obamawhitehouse.archives.gov/blog/author/stephanie-valencia",
        "https://obamawhitehouse.archives.gov/blog/author/stub",
        "https://obamawhitehouse.archives.gov/blog/author/tanya-somanader",
        "https://obamawhitehouse.archives.gov/blog/author/tina-tchen",
        "https://obamawhitehouse.archives.gov/blog/ladders-of-opportunity",
        "https://obamawhitehouse.archives.gov/briefing-room/presidential-actions/executive-orders",
        "https://obamawhitehouse.archives.gov/briefing-room/presidential-actions/presidential-memoranda",
        "https://obamawhitehouse.archives.gov/briefing-room/presidential-actions/proclamations",
        "https://obamawhitehouse.archives.gov/energy/news",
        "https://obamawhitehouse.archives.gov/featured-videos",
        "https://obamawhitehouse.archives.gov/healthreform/blog",
        "https://obamawhitehouse.archives.gov/healthreform/press",
        "https://obamawhitehouse.archives.gov/hispanic/blog",
        "https://obamawhitehouse.archives.gov/jewishamericans/blog",
        "https://obamawhitehouse.archives.gov/letters",
        "https://obamawhitehouse.archives.gov/lgbt/blog",
        "https://obamawhitehouse.archives.gov/nativeamericans/blog",
        "https://obamawhitehouse.archives.gov/ondcp/news-releases",
        "https://obamawhitehouse.archives.gov/ondcp/speeches",
        "https://obamawhitehouse.archives.gov/photos",
        "https://obamawhitehouse.archives.gov/youngafrica/blog",
        "https://obamawhitehouse.archives.gov/youngamericans/blog",
        # Found via /blog/authors (a person-directory listing of every blog
        # author, NOT itself seeded here - its "items" are themselves
        # listing pages, not content) - these 42 author blogs were never
        # surfaced by nav wandering at all, only by walking that
        # directory's own pagination as a one-off discovery pass.
        "https://obamawhitehouse.archives.gov/blog/author/Tania-Simoncelli",
        "https://obamawhitehouse.archives.gov/blog/author/alefiyah-mesiwala",
        "https://obamawhitehouse.archives.gov/blog/author/alissa-ko",
        "https://obamawhitehouse.archives.gov/blog/author/amanda-lucidon",
        "https://obamawhitehouse.archives.gov/blog/author/anita-breckenridge",
        "https://obamawhitehouse.archives.gov/blog/author/asra-najam",
        "https://obamawhitehouse.archives.gov/blog/author/bess-evans",
        "https://obamawhitehouse.archives.gov/blog/author/brian-mosteller",
        "https://obamawhitehouse.archives.gov/blog/author/candace-vahlsing",
        "https://obamawhitehouse.archives.gov/blog/author/cassandra-marketos",
        "https://obamawhitehouse.archives.gov/blog/author/christine-harada-0",
        "https://obamawhitehouse.archives.gov/blog/author/christy-goldfuss",
        "https://obamawhitehouse.archives.gov/blog/author/contessa-jin",
        "https://obamawhitehouse.archives.gov/blog/author/cristin-dorgelo",
        "https://obamawhitehouse.archives.gov/blog/author/david-simas",
        "https://obamawhitehouse.archives.gov/blog/author/denis-mcdonough",
        "https://obamawhitehouse.archives.gov/blog/author/fred-p-hochberg",
        "https://obamawhitehouse.archives.gov/blog/author/ginette-maga%C3%B1a",
        "https://obamawhitehouse.archives.gov/blog/author/jamal-brown",
        "https://obamawhitehouse.archives.gov/blog/author/jason-goldman",
        "https://obamawhitehouse.archives.gov/blog/author/jennifer-lee",
        "https://obamawhitehouse.archives.gov/blog/author/jesse-moore",
        "https://obamawhitehouse.archives.gov/blog/author/jillian-maryonovich",
        "https://obamawhitehouse.archives.gov/blog/author/john-p-holdren",
        "https://obamawhitehouse.archives.gov/blog/author/katy-kale",
        "https://obamawhitehouse.archives.gov/blog/author/keith-maley",
        "https://obamawhitehouse.archives.gov/blog/author/kimberlyn-leary",
        "https://obamawhitehouse.archives.gov/blog/author/laura-s-h-holgate",
        "https://obamawhitehouse.archives.gov/blog/author/maya-shankar",
        "https://obamawhitehouse.archives.gov/blog/author/michael-d-smith",
        "https://obamawhitehouse.archives.gov/blog/author/michael-robertson",
        "https://obamawhitehouse.archives.gov/blog/author/parker-liautaud",
        "https://obamawhitehouse.archives.gov/blog/author/paulette-aniskoff",
        "https://obamawhitehouse.archives.gov/blog/author/rohan-patel",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-ashton-carter",
        "https://obamawhitehouse.archives.gov/blog/author/secretary-john-kerry",
        "https://obamawhitehouse.archives.gov/blog/author/sheila-nix",
        "https://obamawhitehouse.archives.gov/blog/author/vice-president-joe-biden",
        "https://obamawhitehouse.archives.gov/blog/author/yohannes-abraham",
    ]

    start_urls = ['https://obamawhitehouse.archives.gov/'] + LISTING_SEEDS

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listing_seed_urls = set(self.LISTING_SEEDS)

    def parse_start_url(self, response):
        """CrawlSpider routes every start_urls response here instead of the
        Rule's own callback. A curated listing seed gets flagged is_listing
        (matching how nav would flag any OTHER discovered listing) and then
        dispatched to the dedicated pagination-walk; every other start_url
        (currently just the homepage) falls through to ordinary parse_nav.
        """
        if response.url in self._listing_seed_urls:
            yield {
                'url': response.url,
                'is_listing': True,
                'depth': response.request.meta.get('depth', 0) if response.request else 0,
            }
            yield from self._walk_listing_pagination(response)
        else:
            yield from self.parse_nav(response)

    def _walk_listing_pagination(self, response):
        """Extract this listing page's items and follow its own pager,
        recursing through subsequent pages via this same callback - ported
        from the old obama_whitehouse_harvest_list.py's parse(). Does NOT
        flag subsequent pagination pages as their own is_listing record -
        only the seed's entry point gets one, via parse_start_url - since a
        1,176-page pagination chain doesn't need 1,176 near-duplicate
        "this is a listing" rows once the section's already flagged once.

        Three known listing templates: teaser-card (.views-row h2/h3 a, e.g.
        blog/author pages), table-based gallery (.views-field-title, e.g.
        photo/video galleries), and person-directory (.views-row
        .views-field-nid a, e.g. /blog/authors - not itself seeded, see the
        LISTING_SEEDS comment above for why).
        """
        links = response.css(
            '.views-row h2 a::attr(href), .views-row h3 a::attr(href)'
        ).getall()
        if not links:
            links = response.css('.views-field-title a::attr(href)').getall()
        if not links:
            links = response.css('.views-row .views-field-nid a::attr(href)').getall()
        if not links:
            return

        rules = self._get_exclusion_rules()
        for href in links:
            url = response.urljoin(href)
            reason = exclusion_rules.match_exclude(url, rules)
            if reason is not None:
                self._log_exclusion(url, reason)
                continue
            yield {'url': url}

        self._census_links(response)

        # .pager-current's immediately-following sibling <li> holds the
        # forward link in both templates (a "Next" link in the teaser-card
        # pager, a numbered page link in the gallery pager) - one selector
        # covers both rather than branching on .pager-next (which the
        # gallery template doesn't use at all). Followed unconditionally,
        # regardless of whether this page's items were excluded - a listing
        # can mix excluded and real items on the same page, and later pages
        # may hold only real ones.
        next_page = response.css('.pager-current + li a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self._walk_listing_pagination)
