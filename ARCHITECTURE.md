# Architecture

This document is for engineers already working in this codebase. Use it to
understand why a specific mechanism behaves the way it does, or what to
watch out for before reusing it on a new site. It is not an onboarding guide,
and not a how-to. For operational steps to harvest or scrape a site, see
[HARVESTING.md](HARVESTING.md).

Every section below follows the same shape: **What** it is, **Why** it
exists, **How** it works, and, where relevant, **Watch out for**: known
gaps, limitations, or decisions with no single universally right answer.

Sections run from the most broadly relevant (what the scraper visibly does:
the files it produces, the rules that shape them) toward the
narrowest and deepest internal mechanisms (specific to `NavHarvesterMixin`
internals).

---

## URL exclusion rules (`archive_crawler/exclusion_rules.py`)

**What.** Every harvest-capable and content spider reads a per-domain YAML
file at `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`, loaded by
`exclusion_rules.load_rules`. See that module's own docstring for the file
format (`extensions`, `rules`, `pagination`, `query_params_allow`), and for
how to structure a new site's file.

**Why.** The `rules:` list and the `extensions`-based `is_web_url` filter are
easy to conflate. This section covers the design rationale that separates
them.

**How it works.**

Both the nav crawler (`NavHarvesterMixin._apply_exclusion_rules`) and the
content spider (`SitemapUrlSpiderMixin._parse_sitemap`, for the sitemap-based
spiders) check `rules:` entries. A single `rules:` entry excludes a URL shape
from the entire pipeline, nav crawl and content scrape alike, with one entry
instead of a duplicate in each. Use this for URLs that are genuinely out of
scope everywhere (a non-English mirror, a known-duplicate alias prefix).

`is_web_url` does extension-based filtering (allow-list or deny-list, per
`extensions.mode`). Both the nav crawler and content spiders use it to tell
real web pages apart from downloadable assets (PDFs, images, and similar).
An allow-list (the default for a known site) is stricter: only listed
extensions pass. A deny-list (used by `generic_crawl_harvest`'s default
rules, since that spider targets an unbounded variety of unknown sites) is
more permissive: it blocks only listed binary or data formats, and passes
everything else. A URL with no extension, or a suffix too long to plausibly
be a real extension, always passes, regardless of mode.

---

## Never pass `-O`/`-o` to a multi-`FEEDS`-entry spider

**What.** A hard rule: never pass Scrapy's `-O`/`-o` CLI flags to any of
this project's 12 in-scope content spiders.

**Why.** Every fused spider (all 8 sitemap-based sites, plus
`obama_whitehouse`/`letsmove`/`trumpwhitehouse`) declares
`custom_settings['FEEDS']` with **two**
entries: a harvest feed (`item_classes: [HarvestItem]`, `fields:
['url']` or `['url', 'is_listing', 'depth']`), and a content feed
(`item_classes: [ArchiveItem]`, the full field list). One
`scrapy crawl <name>` run produces both CSVs from the one item stream this
way, each filtered to its own item type.

Scrapy's `-O`/`-o` CLI flags do not add a feed alongside that setting. They
**replace `FEEDS` wholesale**, with a single generic feed that has no
`item_classes` filter and no explicit `fields` list. Every item type the
spider yields (both `HarvestItem` and `ArchiveItem`) lands in that one
file. A `HarvestItem` gets yielded before the `Request` for its matching
content page even completes, so the CSV writer's field shape locks onto
`HarvestItem`'s own fields (`depth`, `is_listing`, `url`). The real
scraped content either goes missing silently, or shows up with blank
`title`/`full_text`/`source_site`, and similar fields, not as an error.

**Confirmation.** The first implementation of
`scrape_index_pipeline`'s `crawl-and-push` mode invoked
`scrapy crawl <name> -O <path>`. It produced a
`clintonwhitehouse1.csv` where all 2,611 rows had an empty `source_site`.
The run discarded every real content row.

**Watch out for.** Never pass `-O`/`-o` to a spider that already has its
own automatic output paths (every content spider in this project, per
"CSV Naming Convention" — the whole point of that convention is that no
run ever needs `-O` for correctness). Only pass it when you deliberately
want to redirect output to a path the spider's own
`custom_settings['FEEDS']` does not already cover.

---

## Push pipeline stages (`archive_crawler/pipeline/`)

**What.** `scrape_index_pipeline` (see README's "Push Pipeline" section for
usage) is a thin CLI over six modules: `registry.py`, `validate.py`,
`crawl_health.py`, `filter_rows.py`, `convert.py`, `push.py`.

**Why.** This project's own responsibility ends at pushing a site's
converted JSONL to S3. A downstream Lambda, closer to the OpenSearch side
of the pipeline, watches that bucket and handles indexing, including any
reconciliation against existing index contents (for example, deleting a
`source_site`'s stale documents before re-indexing). Nothing here deletes
or reconciles index contents itself.

**How it works**, stage by stage:

- **`registry.py`** — `list_sites()` enumerates every content spider through
  `scrapy.spiderloader.SpiderLoader`, keyed by `source_site` (this excludes
  `generic_crawl`/`generic_crawl_harvest`/`sitemap_harvest`, which have no
  fixed site identity). `resolve(site_arg)` looks a site up by either
  spider name or `source_site`.
- **`validate.py`** — a 0-row CSV always raises `ValidationError`, with no
  override, whatever the cause (a failed crawl, a bad `--csv` path, a
  truncated file). A push has no content to justify going ahead. Beyond
  that, every `source_site` value present must be a known
  site, and `url` must be present and well-formed (it becomes the
  OpenSearch document ID downstream). Raises `ValidationError` listing
  every problem found, not just the first. `full_text`/`teaser_text`
  go unvalidated. An earlier bare-URL-regex check on those fields
  (meant to catch a column swap) produced a false positive on a real
  page whose only body content is an outbound link, and blocked an entire
  site's push over one legitimate row. Removed in favor of validating
  `url` instead. Narrower than
  `~/git/nara/scripts/validate-opensearch-csv.py` (invisible-unicode,
  HTML-tag, HTML-entity, missing-space, "Continue reading" checks). That
  script audits CSVs already pulled back out of the live index. This one
  only gates whether a row is safe to push at all.
- **`crawl_health.py`** — runs right after `validate.py`, and checks the
  site's sibling `*_dropped.csv` in three tiers. The first two tiers
  always run, with no override, not even `--bypass`. First: the
  dropped-log must exist at all. `ExclusionLoggingMixin` writes it on
  every clean `spider_closed`, even with zero data rows, so a missing
  file means the crawl crashed before finishing (an OOM kill, a
  segfault, a killed SSH session), not that it ran clean. A crashed
  crawl can still leave a real, nonzero main CSV behind, since `FEEDS`
  writes rows as they get scraped, not only at the end, so this catches
  a case `validate.py`'s own zero-row check cannot. A hand-built `--csv`
  needs a placeholder dropped-log (header row, zero data rows) alongside
  it to pass. Second: any `critical_sitemap:*` row (`ArchiveSpiderMixin._log_sitemap_fetch_error`
  in `base.py`, for a failed top-level sitemap or sub-sitemap request) or
  `critical_pagination:*` row (`NavHarvesterMixin._log_pagination_fetch_error`
  in `nav_harvest.py`, for a failed listing-pagination continuation
  request). Either one means a lost request cost every page past it, not
  just one page, so a single matching row always raises `CrawlHealthError`.
  Each covers both a real server/network error and its matching
  empty-response case (`EmptySitemapResponseError`/
  `EmptyPaginationResponseError`) under the same prefix — see the module
  docstring for the full split. The third tier, skipped only by
  `--bypass`, counts ordinary `http_5xx`/`network_error:*` rows on a
  content-page fetch, except `network_error:EmptyResponseError`. That one
  reason stays excluded on purpose: it turned up persistent, on the same
  URLs, unchanged for months, on several Clinton-era sites. Counting it
  would abort every future push for those sites, forever, since a
  permanently broken page never resolves the way a transient failure
  does. This tier raises `CrawlHealthError` at `--error-threshold` or
  more matching rows. The default threshold comes from the site's spider
  class, its `ERROR_THRESHOLD` attribute (see
  `archive_crawler/spiders/base.py`), normally 1 through
  `ArchiveSpiderMixin`. A spider overrides it to set its own default.
  `--error-threshold` on the CLI always wins over both. `--bypass` skips
  only this third tier. It never skips the first two tiers, and never
  skips the 0-row check `validate.py` already ran.
- **`filter_rows.py`** — reads `archive_crawler/filter_rules/<source_site>.yml`
  (`drop_if_all_present: [no_body]`, or `[]` for "never drop") to decide
  which `warnings` labels (see README's "Warnings Column") drop a row
  before conversion. A row gets dropped only when its warning set is a
  *superset* of that list (a two-label entry requires both labels
  present, not either). A `source_site` with no committed file raises,
  rather than silently defaulting either way. `--filter-rules-file`/
  `--filter-rules-mode` overlay a per-run override on the committed file,
  without editing it, the same shape as `exclusion_rules.py`'s own overlay
  for spiders.
- **`convert.py`** — maps a CSV row to an `archive_content_v2` document
  field (`source_type` to `source_type_id` is the one renamed field.
  `convert.py` drops `warnings`, and it is not on the live mapping).
  `id`/`document_type`/`source`/`changed` still go unpopulated. All 12
  in-scope sites now have real documents live in the index (2026-08-11/12
  full rescrape, 423,549 documents), with this gap in every one of them.
  This is a live production gap now, not a theoretical future one, though
  it has not blocked indexing, `source_site.keyword` counts, or search
  from working.

**Watch out for.** `push.py` uploads to a `<source_site>/<source_site>.jsonl`
key in the `NARA_S3_BUCKET` bucket (`nara-crawl-data`), one folder per site.
`convert.py`'s `id`/`document_type`/`source`/`changed` gap (see above) is
still open, live in production across all 12 sites now, but does not block
a real upload or search from working today.
Credentials: this project uses boto3's own default provider chain as-is
(real environment variables first, a shared credentials file after). See
`.env.example` for the gitignored `.env` fallback that points boto3 at a
non-default credentials file or profile, and configures the bucket and
region. Use it only when the real environment has no AWS credentials of
its own.

---

## Listing fingerprint dedup (`NavHarvesterMixin`)

**What.** `NavHarvesterMixin` (`archive_crawler/spiders/nav_harvest.py`)
powers every no-sitemap nav harvester. It fingerprints paginated listing
widgets, so that the same listing, embedded on many different pages, gets
walked once instead of once per embed.

**Why.** A site's navigation graph routinely embeds the *same* paginated
listing (a "browse all videos" widget, a "recent posts" block) on thousands
of distinct pages. Following each embed's pagination independently would
re-walk that listing's full item range once per embed: a fan-out blowup,
not a bug in the target site.

**How it works.**

A subclass opts in by setting three class attributes together:

- `LISTING_VIEW_LINK_EXTRACTOR` — a `LinkExtractor` scoped to the container a
  listing's item rows and pager share (e.g. Drupal Views' `.view` wrapper).
- `LISTING_CONTAINER_SELECTOR` — a plain CSS selector string for that same
  container (e.g. `'.view'`). This stays separate from `LISTING_VIEW_LINK_EXTRACTOR`,
  rather than read back from its internal `restrict_css`. Scrapy
  translates that to XPath and merges it into `restrict_xpaths` at construction time,
  indistinguishable there from a directly supplied XPath, so it is not a
  reliable place to recover a CSS selector from.
- `LISTING_PAGER_SELECTOR` — a CSS selector that only matches when a real,
  populated pager is present (e.g. `.pager-current`).

A subclass must set all three. A container without a populated pager is not enough on
its own to identify a listing. An ordinary content page that merely embeds
a single-item "related content" widget can render inside the same container
with real links but no pager, and would false-positive as a listing without
the pager check. The default for all three is `None`, which disables the
feature entirely: `parse_nav` never flags a listing, never fingerprints, and
follows every extracted link unconditionally, a plain full-link-follow
crawl with no listing-awareness.

When enabled, `parse_nav` evaluates every `LISTING_CONTAINER_SELECTOR` match
on the page independently, not the page as a whole. A page carrying more
than one genuinely paginated listing gets one fingerprint check, and
potentially one walk, per container. For each container with a populated
pager:

1. Flags the page in the output (`is_listing=True` plus `depth`. `True` if
   *any* container on the page has a populated pager).
2. Extracts that container's own item-URL set through `_listing_pagination_items`
   (subclass-implemented, template-specific, scoped to the one container
   Selector. **Not** the wider set `LISTING_VIEW_LINK_EXTRACTOR` finds,
   which also picks up the container's own numbered pager links. Those
   point back to the current permalink, and would make otherwise-identical
   listings hash differently).
3. Hashes that set (sha1 of the sorted URLs), and combines it with the
   container's own persistent Drupal `view-id`/`view-display-id` (parsed
   from its class attribute) into a composite `(view_id, display_id,
   item_hash)` key. Requiring `view_id`/`display_id` to also match, not
   item-hash alone, means two *different* Views configurations whose entry
   pages happen to render an identical item set (for example, a "recent
   posts" view and a "browse all" view, both sorted the same way) no
   longer collide just because their top-N items coincide. The underlying
   view identity has to agree too. A container without this markup (for
   example, a non-Drupal site) degrades to `(None, None, item_hash)`, the
   same item-hash-only behavior as before this key existed.
4. If the key has not been seen this run, walks that container's full
   pagination through `_walk_listing_pagination`, fetching every extracted
   item through `parse_nav` itself (so an item's own outbound links get
   explored too). If the key has already been seen, that container gets
   flagged, and nothing inside it gets walked or followed.

`_walk_listing_pagination` re-locates "the same" container on each
subsequent pagination page by matching `view_id`/`display_id` first, falling
back to positional index only when no container's identity matches. The
positional fallback assumes container order stays stable across a listing's
own paginated pages (the same template renders its blocks in the same order
on every page). That holds up for how Views-rendered pages work in
practice, but is not logically guaranteed, which is why the identity match
runs first.

No link inside a matched container, item rows or pager and filter controls,
ever gets followed by `parse_nav`'s ordinary link-following loop. Only the
dedicated walk above follows them (this pooling still runs page-wide
through `LISTING_VIEW_LINK_EXTRACTOR`, since pooling for "do not
double-follow" purposes is harmless, even though fingerprinting and walking
run per-container).
`_seen_listing_fingerprints` stays in memory, scoped to one crawl run.

`FORCE_SKIP_LISTING_URLS` is a manual escape hatch (empty by default): a URL
in this set always gets flagged `is_listing`, and never gets auto-walked,
regardless of fingerprint, for a case where fingerprinting misses a real
duplicate. `LISTING_MAX_PAGES` (default 2000) bounds a single
container's pagination walk as a defense-in-depth cap against an unbounded
shared catalog.

**Deciding whether to enable this for a new site.** Enabling this feature on
a subclass is mechanically trivial: set three class attributes, and
implement two small methods. Whether to enable it is a separate question
that depends entirely on the target site's own listing structure, and is
never a safe default in either direction:

- Leaving it disabled reverts to unconditional full-link-follow. That is
  exactly the shared-catalog fan-out failure mode this mechanism exists to
  prevent, if the site has one.
- Enabling it is not risk-free either — see "Watch out for" below.

Before deciding either way for a given site, run the same kind of discovery
already done for obamawhitehouse and letsmove. Confirm whether a real
shared-catalog fan-out risk actually exists there, and, if enabling, check
the limitations below against that site's specific listing templates (for
example, bucket flagged listings by URL-prefix, and live-refetch each
shallow one to compare fingerprints. That is the same check used to ground
the confirmation below).
Do not enable or disable this mechanism for a new site on convenience or
default alone.

**Watch out for.**

*URL aliasing.* The fingerprint keys off exact item-URL-set identity
(plus view identity, see above), not "is this the same underlying view
reached a different way." Two URL paths that alias the identical view hash
differently, and each get walked in full. Confirmed on letsmove, where
`/blog/all` and `/blog/all/all` render overlapping-but-not-identical content
at different page sizes, and on obamawhitehouse, where a legacy
`/realitycheck` alias prefix mirrors already-crawled content (including the
site's shared video and photogallery catalogs) under a different address.

Deliberately not fixed. The cost stays bounded: linear in however many
distinct aliases a site actually defines for one view (in practice, a
handful), not the exponential per-embedding-permalink blowup this mechanism
exists to prevent, which stays unaffected (see "How it works" above). Scrapy's
own URL-level dupefilter also still collapses the actual content items
regardless of which alias's pagination found them first, so ordinary
aliases mostly just waste some redundant pagination requests. Where an alias
is expensive enough to matter (`/realitycheck`, mirroring the video and
photogallery catalogs at roughly 740 and 35 pages each), the fix is a
targeted `rules:` exclusion once found (see `www.obamawhitehouse.yml`), not
a change to this mechanism. The extra items an unexcluded alias surfaces in
a harvest are themselves the signal that exposes it for that exclusion.
Building automatic alias detection here would remove exactly the visibility
that caught `/realitycheck` in the first place.

*Facet/filter links.* `parse_nav`'s ordinary link-following loop
(`_follow_ordinary_links`) has no concept of "pager link" versus "facet or
filter link" versus "ordinary content link." It follows every non-excluded
link on the page. For a site that also enables listing-fingerprint dedup,
this is usually harmless in practice: `LISTING_VIEW_LINK_EXTRACTOR`'s
`restrict_css` scope typically also covers any facet controls rendered
inside the same listing container, so those get pooled into `view_urls`,
and the ordinary loop skips them the same as pager and item links.
`obama_whitehouse.py`/`letsmove.py` run this way in production without
incident. But that pooling is *incidental*, not a general guarantee: it
only fires when a container has a populated `LISTING_PAGER_SELECTOR` match,
and it only covers facet controls that actually render inside
`LISTING_VIEW_LINK_EXTRACTOR`'s scope.

Confirmed live on `open.obamawhitehouse.archives.gov` (which has no
listing-fingerprint dedup enabled at all): the site's Facet API
exposed-filter widget renders in a sidebar panel, structurally separate
from the results-and-pager container. One of its pages
(`/group/data-catalog`) has no pager on it at all, so even scoping
`LISTING_VIEW_LINK_EXTRACTOR` to cover both regions would not help,
since the pager-presence gate that triggers pooling never fires there.
Each facet-filter combination is otherwise a distinct URL, and Scrapy's
dupefilter has no reason to collapse it. Following them all is a real
combinatorial-blowup risk, not just noise.

The current mitigation is a `rules:` exclusion, not the fingerprint
mechanism. See `exclusion_rules/open.obamawhitehouse.yml` for the two
patterns needed (`/field_[a-z_]+/` for path-based facets, `f%5B\d+%5D=`
for Drupal's Facet API query-string convention). When building a new
no-sitemap site, check for a facet or filter UI during discovery (step 1
in HARVESTING.md) the same way you would check for pagination. Do not
assume dedup, if enabled, will incidentally cover it, without confirming
the facet controls actually render inside the pooled container scope.

---

## Non-HTML responses in `parse_nav`

**What.** A guard against `parse_nav` (and its pagination-walk counterpart)
crashing when a followed link turns out not to be an HTML page.

**Why.** `parse_nav`, `_detect_listing_containers`, and
`_follow_ordinary_links` all call `response.css(...)`, or a `LinkExtractor`'s
`extract_links(response)`, unconditionally, assuming an HTML document.
`is_web_url`'s extension-based check (see below) cannot fully guard this on
its own. It only inspects the URL, not what the server actually returns, so
a URL with no extension hinting at its real content type (a JSON API
endpoint, a raw data file served from an extension-less path) can still
reach these calls.

**How it works.** Two distinct failure shapes both get logged as
`non_text_response` (the same reason `ArchiveSpiderMixin._is_excluded_response`
already uses for content spiders), rather than crashing the response:

- A plain binary `Response` has no `.css()`/`.selector` at all.
  `isinstance(response, scrapy.http.TextResponse)` catches this.
- A JSON response *is* a `TextResponse` (isinstance alone will not catch
  it), but Scrapy's auto-selector gives it a dict root instead of an lxml
  tree. Confirmed live through `open.obamawhitehouse.archives.gov`'s DKAN
  JSON API (`/api/3/action/package_show?id=...`, linked from every dataset
  page), which crashed with `AttributeError: 'dict' object has no attribute
  'iter'` before this guard existed. `response.selector.type == 'json'`
  catches this one. XML and plain-text responses are fine either way.
  Parsel falls back to a working HTML-parsed root for both, so this check
  is deliberately JSON-specific, not a blanket "must be real HTML" gate.

Both checks live at the top of `parse_nav` and `_walk_listing_pagination`
(nav_harvest.py). The latter needs its own copy, since it registers as
its own Scrapy callback for pagination-page requests, and never routes
through `parse_nav`.

**Watch out for.** A site-specific `rules:` entry (for example,
`open.obamawhitehouse.yml`'s `/api/` and `/download` patterns) is still
worth adding for a *known* non-HTML endpoint, even with this guard in
place. It saves the wasted request entirely, rather than
fetching, then gracefully excluding. This guard is the safety net for
whatever a new site's own discovery pass does not happen to catch.
