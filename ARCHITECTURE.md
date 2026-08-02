# Architecture

Mechanism-level reference for how this crawler's harder pieces work and what
to watch out for when applying them to a new site. For operational
how-to (steps to harvest/scrape a new or existing site), see
[HARVESTING.md](HARVESTING.md).

---

## Listing fingerprint dedup (`NavHarvesterMixin`)

`NavHarvesterMixin` (`archive_crawler/spiders/nav_harvest.py`) powers every
no-sitemap nav harvester. Its core problem: a site's navigation graph
routinely embeds the *same* paginated listing (a "browse all videos"
widget, a "recent posts" block) on thousands of distinct pages. Following
each embed's pagination independently would re-walk that listing's full
item range once per embed — a fan-out blowup, not a bug in the target site.

### How it works

A subclass opts in by setting three class attributes together —
`LISTING_VIEW_LINK_EXTRACTOR` (a `LinkExtractor` scoped to the container a
listing's item rows and pager share, e.g. Drupal Views' `.view` wrapper),
`LISTING_CONTAINER_SELECTOR` (a plain CSS selector string for that same
container, e.g. `'.view'`), and `LISTING_PAGER_SELECTOR` (a CSS selector
that only matches when a real, populated pager is present, e.g.
`.pager-current`). `LISTING_CONTAINER_SELECTOR` is kept separate from
`LISTING_VIEW_LINK_EXTRACTOR` rather than read back from its internal
`restrict_css`, which Scrapy translates to XPath and merges into
`restrict_xpaths` at construction time — indistinguishable there from a
directly-supplied XPath, so not a reliable place to recover a CSS selector
from. All three must be set; a container without a populated pager isn't
enough on its own — an ordinary content page that merely embeds a
single-item "related content" widget can render inside the same container
with real links but no pager, and would false-positive as a listing without
the pager check.

`parse_nav` evaluates every `LISTING_CONTAINER_SELECTOR` match on the page
independently, not the page as a whole — a page carrying more than one
genuinely paginated listing gets one fingerprint check and, potentially, one
walk, per container. For each container with a populated pager:

1. Flags the page in the output (`is_listing=True` + `depth` — `True` if
   *any* container on the page has a populated pager).
2. Extracts that container's own item-URL set via `_listing_pagination_items`
   (subclass-implemented, template-specific, scoped to the one container
   Selector — **not** the wider set `LISTING_VIEW_LINK_EXTRACTOR` finds,
   which also picks up the container's own numbered pager links; those
   point back to the current permalink and would make otherwise-identical
   listings hash differently).
3. Hashes that set (sha1 of the sorted URLs), and combines it with the
   container's own persistent Drupal `view-id`/`view-display-id` (parsed
   from its class attribute) into a composite `(view_id, display_id,
   item_hash)` key.
4. If the key hasn't been seen this run, walks that container's full
   pagination via `_walk_listing_pagination`, fetching every extracted item
   through `parse_nav` itself (so an item's own outbound links get explored
   too). If the key has already been seen, that container is flagged and
   nothing inside it is walked or followed.

Requiring `view_id`/`display_id` to also match — not item-hash alone — means
two *different* Views configurations whose entry pages happen to render an
identical item set (e.g. a "recent posts" view and a "browse all" view, both
sorted the same way) no longer collide just because their top-N items
coincide; the underlying view identity has to agree too. A container without
this markup (e.g. a non-Drupal site) degrades to `(None, None, item_hash)` —
the same item-hash-only behavior as before this key existed.

`_walk_listing_pagination` re-locates "the same" container on each
subsequent pagination page by matching `view_id`/`display_id` first, falling
back to positional index only if no container's identity matches. The
positional fallback assumes container order is stable across a listing's own
paginated pages (the same template renders its blocks in the same order on
every page) — reasonable for how Views-rendered pages work in practice, but
not logically guaranteed, which is why the identity match is tried first.

No link inside a matched container — item rows or pager/filter controls —
is ever followed by `parse_nav`'s ordinary link-following loop; only via the
dedicated walk above (this pooling still runs page-wide via
`LISTING_VIEW_LINK_EXTRACTOR`, since pooling for "don't double-follow"
purposes is harmless even though fingerprinting/walking are per-container).
`_seen_listing_fingerprints` is in-memory, scoped to one crawl run.

`FORCE_SKIP_LISTING_URLS` is a manual escape hatch (empty by default): a URL
in this set is always flagged `is_listing` and never auto-walked, regardless
of fingerprint, for a case where fingerprinting is confirmed to miss a real
duplicate. `LISTING_MAX_PAGES` (default 2000) bounds a single container's
pagination walk as a defense-in-depth cap against an unbounded shared
catalog.

The default for `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR`/
`LISTING_PAGER_SELECTOR` is `None`, which disables the feature entirely:
`parse_nav` never flags a listing, never fingerprints, and follows every
extracted link unconditionally — a plain full-link-follow crawl with no
listing-awareness.

### Decision rule: discovery before enabling or disabling

Enabling this feature on a subclass is mechanically trivial — set three
class attributes and implement two small methods. Whether to enable it is a
separate question that depends entirely on the target site's own listing
structure, and is never a safe default in either direction:

- Leaving it disabled reverts to unconditional full-link-follow, which is
  exactly the shared-catalog fan-out failure mode this mechanism exists to
  prevent, if the site has one.
- Enabling it is not risk-free either — see the known limitation below.

Before deciding either way for a given site, run the same kind of discovery
already done for obamawhitehouse and letsmove: confirm whether a real
shared-catalog fan-out risk actually exists there, and, if enabling, check
the limitation below against that site's specific listing templates (e.g.
bucket flagged listings by URL-prefix and live-refetch each shallow one to
compare fingerprints, the same check used to ground the confirmation below).
Don't enable or disable this mechanism for a new site on convenience or
default alone.

### Known limitation

**URL aliasing.** The fingerprint is keyed on exact item-URL-set identity
(plus view identity, see above), not "is this the same underlying view
reached a different way." Two URL paths that alias the identical view hash
differently and each get walked in full — confirmed on letsmove, where
`/blog/all` and `/blog/all/all` render overlapping-but-not-identical content
at different page sizes, and on obamawhitehouse, where a legacy
`/realitycheck` alias prefix mirrors already-crawled content (including the
site's shared video/photogallery catalogs) under a different address.

Deliberately not fixed. The cost is bounded — linear in however many
distinct aliases a site actually defines for one view (in practice, a
handful), not the exponential per-embedding-permalink blowup this mechanism
exists to prevent, which is unaffected (see "How it works" above). Scrapy's
own URL-level dupefilter also still collapses the actual content items
regardless of which alias's pagination found them first, so ordinary
aliases mostly just waste some redundant pagination requests. Where an alias
is expensive enough to matter (`/realitycheck`, mirroring the video/
photogallery catalogs at ~740/~35 pages each), the fix is a targeted
`rules:` exclusion once found (see `www.obamawhitehouse.yml`), not a change
to this mechanism — the extra items an unexcluded alias surfaces in a
harvest are themselves the signal that exposes it for that exclusion, and
building automatic alias detection here would remove exactly the visibility
that caught `/realitycheck` in the first place.

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
