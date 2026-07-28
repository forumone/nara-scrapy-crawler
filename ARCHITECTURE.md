# Architecture

Mechanism-level reference for how this crawler's harder pieces work and what
to watch out for when applying them to a new site. For operational
how-to (steps to harvest/scrape a new or existing site), see
[HARVESTING.md](HARVESTING.md).

---

## Listing fingerprint dedup (`NavHarvesterMixin`)

`NavHarvesterMixin` (`archive_crawler/spiders/base.py`) powers every
no-sitemap nav harvester. Its core problem: a site's navigation graph
routinely embeds the *same* paginated listing (a "browse all videos"
widget, a "recent posts" block) on thousands of distinct pages. Following
each embed's pagination independently would re-walk that listing's full
item range once per embed — a fan-out blowup, not a bug in the target site.

### How it works

A subclass opts in by setting two class attributes together —
`LISTING_VIEW_LINK_EXTRACTOR` (a `LinkExtractor` scoped to the container a
listing's item rows and pager share, e.g. Drupal Views' `.view` wrapper)
and `LISTING_PAGER_SELECTOR` (a CSS selector that only matches when a real,
populated pager is present, e.g. `.pager-current`). Both must be set; either
one alone isn't enough — an ordinary content page that merely embeds a
single-item "related content" widget can render inside the same container
with real links but no pager, and would false-positive as a listing without
the pager check.

When both match on a page, `parse_nav`:

1. Flags the page in the output (`is_listing=True` + `depth`).
2. Extracts the page's own item-URL set via `_listing_pagination_items`
   (subclass-implemented, template-specific — **not** the wider set
   `LISTING_VIEW_LINK_EXTRACTOR` finds, which also picks up the container's
   own numbered pager links; those point back to the current permalink and
   would make otherwise-identical listings hash differently).
3. Hashes that set (sha1 of the sorted URLs) into a fingerprint.
4. If the fingerprint hasn't been seen this run, walks the listing's full
   pagination via `_walk_listing_pagination`, fetching every extracted item
   through `parse_nav` itself (so an item's own outbound links get explored
   too). If the fingerprint has already been seen, the page is flagged and
   nothing inside the container is walked or followed.

No link inside the matched container — item rows or pager/filter controls —
is ever followed by `parse_nav`'s ordinary link-following loop; only via the
dedicated walk above. `_seen_listing_fingerprints` is in-memory, scoped to
one crawl run.

`FORCE_SKIP_LISTING_URLS` is a manual escape hatch (empty by default): a URL
in this set is always flagged `is_listing` and never auto-walked, regardless
of fingerprint, for a case where fingerprinting is confirmed to miss a real
duplicate. `LISTING_MAX_PAGES` (default 2000) bounds a single listing's
pagination walk as a defense-in-depth cap against an unbounded shared
catalog.

The default for both `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_PAGER_SELECTOR`
is `None`, which disables the feature entirely: `parse_nav` never flags a
listing, never fingerprints, and follows every extracted link
unconditionally — a plain full-link-follow crawl with no listing-awareness.

### Decision rule: discovery before enabling or disabling

Enabling this feature on a subclass is mechanically trivial — set two class
attributes and implement two small methods. Whether to enable it is a
separate question that depends entirely on the target site's own listing
structure, and is never a safe default in either direction:

- Leaving it disabled reverts to unconditional full-link-follow, which is
  exactly the shared-catalog fan-out failure mode this mechanism exists to
  prevent, if the site has one.
- Enabling it is not risk-free either — see the known limitations below,
  each of which can under-count content on the wrong listing shape.

Before deciding either way for a given site, run the same kind of discovery
already done for obamawhitehouse and letsmove: confirm whether a real
shared-catalog fan-out risk actually exists there, and, if enabling, check
each limitation below against that site's specific listing templates (e.g.
bucket flagged listings by URL-prefix and live-refetch each shallow one to
compare fingerprints, the same check used to ground the confirmations
below). Don't enable or disable this mechanism for a new site on
convenience or default alone.

### Known limitations

**URL aliasing.** The fingerprint is keyed on exact item-URL-set identity,
not "is this the same underlying view reached a different way." Two URL
paths that alias the identical view hash differently and each get walked in
full — confirmed on letsmove, where `/blog/all` and `/blog/all/all` render
the same content but produce different fingerprints. Usually low-impact,
since Scrapy's own URL-level dupefilter still collapses the actual content
items regardless of which pagination path found them first — so this
mostly wastes redundant pagination requests, not final content accuracy.
Not always compensated: obamawhitehouse's legacy `/realitycheck` alias
prefix (see below) hits this same gap far more expensively, and is handled
by excluding the alias prefix outright via `rules:` rather than relying on
the dupefilter.

**Promoted/full-archive collision.** The fingerprint is keyed on a single
page's item-URL *set*, order-independent, with no awareness of anything
beyond that one page. If two genuinely different listings (different total
item counts) happen to render an identical item set on their own entry page
— e.g. a "recent posts" view showing only promoted content and a
"browse all" view showing the full archive, both sorted the same way, so
both entry pages display the same top-N items — this silently drops
content, not just wastes requests. Whichever listing's entry page is
discovered first registers the fingerprint and gets walked correctly; the
other's entry page hashes to the same fingerprint and is flagged-and-skipped
permanently. There is no dupefilter safety net here, unlike URL aliasing
above: the second listing's exclusive tail content is never fetched from
any path. Checked directly against obamawhitehouse (bucketed every flagged
listing by URL prefix, live-refetched the shallowest candidate in each
bucket, compared fingerprints) with no confirmed instance found there, but
this was not an exhaustive pairwise check across every flagged listing, and
does not rule out a collision between two listings that don't share a URL
prefix at all.

**Co-located listings.** Every step of this mechanism operates page-wide,
not per-`.view`-container: the pager check looks for a pager anywhere on
the page, not inside one specific container; the view-link extractor scans
every matching container on the page; item extraction and next-page lookup
run unscoped queries across the whole document and take the first match in
document order. A page carrying two genuinely distinct, independently
paginated listings is therefore not modeled as two listings at all — both
merge into one fingerprint, and the walk only ever follows one pager chain.
Confirmed to occur on obamawhitehouse's `/energy/news`, which renders two
Views blocks side by side; harmless there only because both listings'
pagers happen to target the same URL (an accidental property of that page's
specific wiring, not something this mechanism understands or guarantees).
A co-located pair with independent pagers would not get the same accidental
protection — the listing whose pager isn't the one being followed could
have tail content silently missed, with nothing to flag it.

Given these limitations remain unfixed, treat automatic listing dedup as
something to verify per site, not to trust by default — see the decision
rule above.

---

## URL exclusion rules (`archive_crawler/exclusion_rules.py`)

Every harvest-capable and content spider reads a per-domain YAML file at
`archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`, loaded by
`exclusion_rules.load_rules`. See that module's own docstring for the file
format (`extensions`, `rules`, `nav_deny`, `pagination`,
`query_params_allow`) and for how a new site's file should be structured;
this section covers the design rationale for two pieces of that schema that
are easy to conflate.

**`rules:` vs. `nav_deny:`.** Both are lists of exclusion patterns, checked
at different points and for different purposes:

- `rules:` entries are checked by both the nav crawler
  (`NavHarvesterMixin._apply_nav_deny`) and the content spider
  (`ArchiveSpiderMixin`/site-specific `start_requests`). A single `rules:`
  entry excludes a URL shape from the entire pipeline — nav crawl and
  content scrape alike — with one entry instead of a duplicate in each.
  Use this for URLs that are genuinely out of scope everywhere (a
  non-English mirror, a known-duplicate alias prefix).
- `nav_deny:` entries are checked only by the nav crawler. Use this for a
  URL shape that should hold the nav crawler back from following it, without
  also excluding the same URL from a content scrape reached some other way
  (e.g. via a `url_file` built independently of the nav crawl). If a URL
  should never be scraped under any path, it belongs in `rules:`, not
  `nav_deny:` — a `nav_deny:`-only exclusion doesn't stop the content spider
  from picking it up elsewhere.

**`is_web_url`.** Extension-based filtering (allow-list or deny-list, per
`extensions.mode`) that both the nav crawler and content spiders use to
distinguish real web pages from downloadable assets (PDFs, images, etc.).
An allow-list (the default for a known site) is stricter — only listed
extensions pass; a deny-list (used by `generic_crawl_harvest`'s default
rules, since that spider targets an unbounded variety of unknown sites) is
more permissive — only listed binary/data formats are blocked, everything
else passes. A URL with no extension, or a suffix too long to plausibly be
a real extension, always passes regardless of mode.
