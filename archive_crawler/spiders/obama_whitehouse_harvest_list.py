import scrapy


class ObamaWhiteHouseHarvestListSpider(scrapy.Spider):
    name = "obama_whitehouse_harvest_list"
    allowed_domains = ["obamawhitehouse.archives.gov"]

    # Hardcoded rather than taken via -a: this is a static archived site, so
    # the true set of listing pages never changes. Add newly-discovered
    # listing candidates (from the nav harvester's is_listing=True output,
    # reviewed) directly here and push, rather than building a dynamic
    # seeds-file mechanism.
    start_urls = [
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
        # Only one seed each for the video and photogallery templates,
        # deliberately - every /photos-and-video/video/* permalink and every
        # /photos-and-video/photogallery/* permalink embeds the *same*
        # sitewide "browse other videos/galleries" catalog (confirmed via
        # diffing item lists across multiple unrelated permalinks - byte
        # identical), not a per-page-scoped one. Seeding more than one of
        # each just re-walks that identical catalog from a different entry
        # point for no new content - this list previously had 230 video and
        # 50 photogallery entries (grown mostly from run 5's listing-candidate
        # promotion, since every permalink trivially passes the is_listing
        # check due to this shared widget) before being trimmed to one each.
        "https://obamawhitehouse.archives.gov/photos-and-video/photogallery/archives-first-families-celebrate-holidays-white-house",
        "https://obamawhitehouse.archives.gov/photos-and-video/video/2009/12/22/gingerbread-white-house",
        "https://obamawhitehouse.archives.gov/recovery/blog",
        "https://obamawhitehouse.archives.gov/strongmiddleclass/blog",
        "https://obamawhitehouse.archives.gov/video/President-Obama-Speaks-to-the-Muslim-World-from-Cairo-Egypt",
        "https://obamawhitehouse.archives.gov/video/President-Obama-on-Urban-Policy",
        # Discovered via the nav harvester run 5 (DEPTH_LIMIT=12, tightened
        # is_listing check), reviewed and confirmed as real listings.
        # Excluded from promotion: 3 congress.gov-linked legislation listings
        # (external content, not indexable via this spider), 3 redundant old
        # /video/ URL aliases (identical items to an already-covered gallery),
        # /blog/authors (0 items under current selectors - different markup,
        # not yet walkable), and one redundant pagination artifact of an
        # already-listed root.
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
        # author - NOT itself added here, see the note above parse() for
        # why) - these 42 author blogs were never surfaced by nav wandering
        # at all, only by walking that directory's own pagination as a
        # one-off discovery pass.
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

    # /blog/authors is a person-directory listing (view-person-listings) of
    # every blog author - deliberately NOT in start_urls above, even though
    # parse() below can now extract it via .views-field-nid. Its "items" are
    # themselves listing pages (/blog/author/X), not content - walking it
    # normally would yield listing-page URLs into harvest-listing.csv as if
    # they were leaf content, the same mistake made and corrected earlier
    # this session (see NavHarvesterMixin's listing_file docstring). Confirmed
    # via a one-off discovery pass (not a start_urls entry) that its 110
    # entries include 42 author blogs not otherwise in start_urls - those 42
    # are listed above individually instead.

    def parse(self, response):
        # Three known listing templates: teaser-card (.views-row h2/h3 a,
        # e.g. blog/author pages), table-based gallery (.views-field-title,
        # e.g. photo/video galleries), and person-directory
        # (.views-field-nid, e.g. /blog/authors - see the note above this
        # method for why that specific page isn't walked as a normal seed
        # despite this selector supporting it). Try each in turn.
        links = response.css(
            '.views-row h2 a::attr(href), .views-row h3 a::attr(href)'
        ).getall()
        if not links:
            links = response.css('.views-field-title a::attr(href)').getall()
        if not links:
            links = response.css('.views-row .views-field-nid a::attr(href)').getall()
        if not links:
            return

        for href in links:
            yield {'url': response.urljoin(href)}

        # .pager-current's immediately-following sibling <li> holds the
        # forward link in both templates (a "Next" link in the teaser-card
        # pager, a numbered page link in the gallery pager) - confirmed
        # empirically on both, so one selector covers both rather than
        # branching on .pager-next (which the gallery template doesn't use
        # at all).
        next_page = response.css('.pager-current + li a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
