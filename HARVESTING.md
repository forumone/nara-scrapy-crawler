# Harvesting a New Site

This document describes the end-to-end process for adding a new site to the crawl
pipeline. Some patterns below split URL discovery and content extraction into two
separate spiders (sitemap-based sites, `generic_crawl_harvest`/`generic_crawl`);
the `NavHarvesterMixin` pattern uses one spider for both, with content extraction
added once selectors are ready. Either way, discovering the full URL list before
writing (or before running) any content-extraction code makes coverage gaps and
unexpected pages visible early, rather than after they've become data problems.

Check for a sitemap first (`/sitemap.xml`, `/sitemap_index.xml`, or a `Sitemap:`
directive in `robots.txt`) — if one exists, skip everything else in this document
and use the sitemap harvester below. The remaining sections (choosing a harvester
pattern, the nav harvester, the generic harvester) are all for sites with **no**
sitemap.

---

## Sitemap harvester

If the site has a sitemap, use `sitemap_harvest` — a single-phase, one-size-fits-all
harvester with no site-specific code to write:

```
scrapy crawl sitemap_harvest \
    -a sitemap_url=https://example.archives.gov/sitemap.xml \
    -a source_site=example
```

It fetches the sitemap (or sitemap index, recursing into all sub-sitemaps),
deduplicates URLs case-insensitively, drops non-web assets (PDFs, images, etc.), and
writes a harvest CSV — one `url` column, one row per content page — without
fetching any content pages itself. Used by all of Clinton (CW1–6), Biden, and GWBush.

Output is automatic, derived from `source_site`: the harvest CSV goes to
`data/example/example_harvest-full.csv`, and any dropped non-web-extension
URLs go to `data/example/example_harvest-dropped.csv` (only written if at
least one URL was actually dropped). This is the one spider in the project
where `-O`/`-o` don't control output at all — pass `-a harvest_file=<path>`
and/or `-a dropped_file=<path>` to override either default explicitly.
Without `source_site`, `harvest_file` becomes required.

Since `sitemap_harvest` never fetches a content page itself, there's no
response here to extract content from inline. Write a separate content
spider (plain `scrapy.Spider` + `ArchiveSpiderMixin`, reading the harvest
CSV as `url_file`) to scrape from it, same as every sitemap-based spider
(CW1–6, Biden, GWBush) does. See README's "Sitemap-Based Archive Spiders"
section for a worked example, and its "Warnings column" section for the
`parse_item` shape (`no_body`/`no_title`/`short_body` flag rather than
exclude).

---

## Choosing a harvester pattern

The following patterns are for sites with no sitemap.

**Use `NavHarvesterMixin`** — the recommended pattern for any no-sitemap
site. One spider handles nav link-following, listing pagination-walking (if
step 1 finds a reliable listing container + pager selector), and content
extraction, all in a single pass over each fetched response. See
"Step-by-step: nav harvester" below.

`generic_crawl_harvest`/`generic_crawl` is starter/example tooling, not a
production-ready alternative for a new site — its selectors are tuned to
site templates already seen in this repo, not universal — so it's excluded
from this decision tree. See README's "Running Locally (Development)"
section if you want to use it for local exploration anyway.

---

## Step-by-step: nav harvester

A single spider class, composing `NavHarvesterMixin` and `ArchiveSpiderMixin`
together, runs one full-site discovery crawl: it finds ordinary content and
listing pages in the same pass, walks a newly-flagged listing's pagination
automatically the first time each listing's item set is seen, and extracts
that page's title/body/teaser on the same fetched response. See
[ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the fingerprint mechanism this relies on, including its known
limitations and the discovery you should do before trusting it against a
new site. This is the recommended pattern for any listing-bearing,
no-sitemap site — `letsmove.py` and `obama_whitehouse.py` are worked
examples.

Content extraction is optional at first: a class composing only
`NavHarvesterMixin` (no `ArchiveSpiderMixin`, no `_scrape_item` method) is a
pure harvest-only spider — useful for auditing the full URL list before
writing any selectors. Add `ArchiveSpiderMixin` and a `_scrape_item` method
to that same class later (step 4) to start getting content on the very next
run — `_maybe_scrape_item` (in `nav_harvest.py`) extracts content whenever
`_scrape_item` exists on the class, skipping it otherwise.

### Step 1 — Discovery

Inspect the live site to answer these questions before writing any code:

- What are the paginated listing sections? (blog, news, press releases, etc.)
  Look for pagination controls and note the URL pattern for page 2+.
- What CSS selector identifies a content link within a listing row? Check
  more than one listing page if the site has more than one visual template
  for listings (e.g. a teaser-card blog archive vs. a table-based photo/video
  gallery can use completely different item-link markup even on the same
  site — `obama_whitehouse.py`'s `_listing_pagination_items` handles
  two such templates).
- What container reliably wraps *both* a listing's item rows and its
  pager/filter controls? (e.g. Drupal Views' own `.view` wrapper) This is
  what `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR` (see step 2)
  use to flag an unknown listing page safely, one container at a time if a
  page carries more than one. Verify it on at least one confirmed listing
  *and* one page you know isn't a listing but embeds some other single-item
  view widget — `.views-row` presence alone is not reliable for this (a
  content page can embed a single-item view and carry the same markup as a
  real listing; see `NavHarvesterMixin`'s docstring). A populated pager/filter
  block inside the container is the actual signal, not the container's mere
  presence.
- What are the top-level nav sections? These become `start_urls` for the nav
  spider — often just the homepage is enough (see step 2).
- Are there path prefixes that should be universally out of scope regardless
  of phase? (e.g. a non-English mirror, `/sites/` Drupal assets) Put these in
  `rules:` in the new site's `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`
  — nav-time exclusion checks `rules ∪ nav_deny`, so a `rules:` entry alone
  covers both the nav crawl and the content spider; reserve `nav_deny` for an
  exclusion that should hold the nav crawler back without also excluding the
  URL from a content scrape reached some other way (see
  `NavHarvesterMixin._apply_nav_deny`).
- What is the domain? Are there subdomains that should be handled by separate spiders?

### Step 2 — Nav + listing discovery crawl

Create `archive_crawler/spiders/<site>.py` using `NavHarvesterMixin`. Set
`SOURCE_SITE` (this class will compose `ArchiveSpiderMixin` too once step 4
adds content extraction, so there's only one `SOURCE_SITE`/one exclusion
rules file for this site), and — if step 1 found a reliable listing-container
selector and pager selector — set all
three of `LISTING_VIEW_LINK_EXTRACTOR`, `LISTING_CONTAINER_SELECTOR`, and
`LISTING_PAGER_SELECTOR` (required together) so the crawler can safely
wander into a listing it's never seen before: it flags the page
(`is_listing=True` in the output) instead of excluding it, and does not
follow any link inside a matched container (item links and pager/filter
controls alike), so discovering a huge listing can't make the crawler fan
out across its full item or pagination range. Instead, the mixin
fingerprints each container's item set (combined with its Drupal
view-id/display-id, if present) and walks its pagination automatically the
first time that combination is seen, fetching every extracted item through
this same crawl — so this one spider's output is already the complete
harvest; no separate listing spider or merge step is needed. See
[ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the full mechanism and its known limitation.
`LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR` alone are not
enough — an ordinary content page that merely embeds a "related content"
widget can render inside the exact same container with real links but no
pager at all; `LISTING_PAGER_SELECTOR` requiring an actual populated pager
is what tells the two apart.

```python
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule
from archive_crawler.items import HarvestItem
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin

class MySiteSpider(NavHarvesterMixin, CrawlSpider):
    name = "mysite"
    allowed_domains = ["mysite.archives.gov"]
    SOURCE_SITE = 'mysite'

    # Output path is automatic, derived from SOURCE_SITE - pass -O <path>
    # on the CLI to override. Only one feed at this step (no content
    # extraction yet); step 4 adds a second FEEDS entry once _scrape_item
    # exists on the class.
    custom_settings = {
        'FEEDS': {
            'data/mysite/mysite_harvest-full.csv': {
                'format': 'csv',
                'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
        },
    }

    # Optional, required together: only set these if step 1 found a
    # reliable listing container AND a pager selector that reliably
    # indicates real pagination (not just any link inside the container).
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['mysite.archives.gov'],
    )
    LISTING_CONTAINER_SELECTOR = '.view'
    LISTING_PAGER_SELECTOR = '.pager-current'

    start_urls = [
        "https://mysite.archives.gov/",
        # A single homepage seed is often enough at a generous DEPTH_LIMIT -
        # add more only if a full (untimed) run still logs genuine
        # depth-exceeded ignores for a section, not preemptively.
    ]

    rules = (
        Rule(
            LinkExtractor(
                allow=r'//mysite\.archives\.gov/',
                allow_domains=['mysite.archives.gov'],
            ),
            callback='parse_nav',
            follow=False,  # omit process_links=; parse_nav applies
                           # _apply_nav_deny directly, and CrawlSpider's own
                           # Rule-dispatch machinery that would call it is
                           # disabled entirely (see the mixin's
                           # custom_settings) - process_links= here would be
                           # dead configuration.
        ),
    )
```

If you override `custom_settings` in a subclass, it **replaces** the
mixin's dict entirely rather than merging with it — keep
`'CRAWLSPIDER_FOLLOW_LINKS': False` in whatever you set, or CrawlSpider's own
built-in link-following silently re-enables for that spider (see the comment
on `NavHarvesterMixin.custom_settings` in `nav_harvest.py` for why).

`listing_file` is still a required argument (`NavHarvesterMixin.__init__`
raises without it) — on a first run there's no prior harvest to seed it
with, so point it at an empty CSV (header row only):

```
echo "url" > data/mysite/mysite_empty-listing.csv

scrapy crawl mysite \
    -a listing_file=data/mysite/mysite_empty-listing.csv \
    -s DEPTH_LIMIT=10 \
    -s DEPTH_PRIORITY=1 \
    -s SCHEDULER_DISK_QUEUE=scrapy.squeues.PickleFifoDiskQueue \
    -s SCHEDULER_MEMORY_QUEUE=scrapy.squeues.FifoMemoryQueue
```

No `-O` needed — `custom_settings['FEEDS']` already defines the output
path. Step 4 adds a second `FEEDS` entry (for content) to that same dict
once `_scrape_item` exists on the class.

The `DEPTH_PRIORITY`/`SCHEDULER_*` flags switch Scrapy's default LIFO
(depth-first) traversal to breadth-first. This matters beyond just even
coverage: Scrapy's dupefilter is a one-time gate — whichever request for a
URL is first to pass it wins, and *that* request's depth is what gets
recorded, with no correction if a shorter path is found later. Under DFS this
can wildly overstate a page's true distance from the seed (a direct child of
an already-visited page was recorded at depth 9 in one real run, having only
ever needed depth 1, because DFS happened to explore a much longer path to it
first). BFS at `CONCURRENT_REQUESTS_PER_DOMAIN=1` makes recorded depth an
exact shortest-path guarantee; raising concurrency reopens a narrow version
of the same race (a deeper-layer candidate can fill an idle slot while a
shallower layer's response is still in flight) but is usually a small,
acceptable error for a discovery-only run, not something to rely on for a
precise claim.

BFS matters only for this initial discovery run, while `DEPTH_LIMIT` is
still being tuned against real depth-exceeded gaps (step 3) — once a site's
`DEPTH_LIMIT` is set comfortably past its longest real pagination chain,
ordering no longer affects completeness, and later runs can drop back to
Scrapy's default DFS scheduler. See README's Obama White House walkthrough
for a site already past this point.

Run this **untimed** (no `CLOSESPIDER_TIMEOUT`) so it actually exhausts the
site rather than stopping mid-traversal — a partial run can't distinguish
"genuinely unreachable within `DEPTH_LIMIT`" from "just didn't get there yet."

### Step 3 — Spot-check listing detections

Filter the harvest CSV for `is_listing=True` and spot-check them for false
positives — a content page that merely embeds a single-item view can still
carry the same container markup as a real listing, though a populated pager
inside it is a much stronger signal than raw item-row markup alone. No
promotion step needed: every flagged listing's pagination is walked
automatically the first time its item-set fingerprint is seen (step 2). If
fingerprinting is ever confirmed to have missed a real duplicate catalog,
add the offending URL to `FORCE_SKIP_LISTING_URLS` rather than introducing a
curated seed list.

Also check the crawl log for `Ignoring link (depth > N)` entries not already
in the harvest CSV — these are genuine gaps cut off purely by `DEPTH_LIMIT`,
not dead ends, and may warrant adding their section root as an additional
`start_urls` seed for a follow-up run (only after confirming the gap, not
preemptively).

### Step 4 — Scrape

Add `ArchiveSpiderMixin` to the **same class** from step 2, and give it a
`_scrape_item(self, response)` method — same role as a standalone spider's
`parse_item`, but called by `_maybe_scrape_item` (in `nav_harvest.py`) on the
response `parse_nav` already fetched for discovery, not a second request.
This pattern has no `url_file` and no separate content-spider file — that's
a different pattern, used by the sitemap-based spiders (see "Sitemap
harvester" above), not by `NavHarvesterMixin` sites.

`_scrape_item` follows the same accumulate-and-continue shape as every
other content spider in this repo: `no_body`/`no_title` don't drop the row
(a real page was fetched — flag it, don't hide it), `short_body` flags a
non-empty body under `SHORT_BODY_THRESHOLD` (default 30 chars, override via
`SHORT_BODY_THRESHOLD` class attr or `-a short_body_threshold=<N>`), and a
missing title falls back to `_slug_title(url)` (last URL path segment,
extension stripped, `-`/`_` → spaces). See README's "Warnings column"
section (or any of `letsmove.py`/`obama_whitehouse.py`) for the full
rationale.

```python
from archive_crawler.items import ArchiveItem, HarvestItem
from archive_crawler.spiders.base import ArchiveSpiderMixin
from archive_crawler.spiders.nav_harvest import NavHarvesterMixin

class MySiteSpider(NavHarvesterMixin, ArchiveSpiderMixin, CrawlSpider):
    name = "mysite"
    allowed_domains = ["mysite.archives.gov"]
    SOURCE_SITE = 'mysite'
    SOURCE_TYPE = 'Archived White House Websites'
    EXCLUSIONS_FILE_SUFFIX = 'exclusions'  # one merged file, not nav+content

    # ... LISTING_*, start_urls, rules, _listing_pagination_items/
    # _listing_pagination_next_url from step 2, unchanged ...

    custom_settings = {
        'DEPTH_LIMIT': 10,
        'CRAWLSPIDER_FOLLOW_LINKS': False,
        # Two named feeds from one run, item_classes-filtered to the
        # matching schema, since both a harvest row and a content row can
        # come from the same page.
        'FEEDS': {
            'data/mysite/mysite_harvest-full.csv': {
                'format': 'csv', 'overwrite': True,
                'item_classes': [HarvestItem],
                'fields': ['url', 'is_listing', 'depth'],
            },
            'data/mysite/mysite.csv': {
                'format': 'csv', 'overwrite': True,
                'item_classes': [ArchiveItem],
                'fields': ['url', 'title', 'teaser_text', 'full_text',
                           'source_site', 'source_type', 'warnings'],
            },
        },
    }

    def _scrape_item(self, response):
        if self._is_excluded_response(response):
            return None
        warnings = []
        body = self._extract_text(response, '#maincontent .content')
        if not body:
            warnings.append('no_body')
        elif len(body) < self._get_short_body_threshold():
            warnings.append('short_body')
        title = response.css('h1').xpath('string(.)').get(default='').strip()
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
```

Run it — same `listing_file` invocation as step 2, no `-O` needed since
`custom_settings['FEEDS']` defines both output paths directly (a cmdline
`-O`/`-o` would override that whole dict rather than adding to it):

```
scrapy crawl mysite \
    -a listing_file=data/mysite/mysite_empty-listing.csv
```

A bare invocation like this always includes content extraction, once
`_scrape_item` exists on the class. To get harvest-only output from a class
that already has `_scrape_item` defined, comment it out (or drop
`ArchiveSpiderMixin`) temporarily — `_maybe_scrape_item` no-ops whenever
`_scrape_item` doesn't exist on the class.

---

## List-first split harvester (considered and rejected)

Not used by any current site in this repo, and not a legitimate fallback
despite earlier framing here as one: it depends on a manually-curated,
up-front list of every listing page, and there's no way to confirm that list
is complete short of ongoing monitoring of crawl output for
suspiciously-repeated content — exactly what the unified pattern's
listing-fingerprint dedup (`NavHarvesterMixin`, above) exists to avoid
needing. If a site's listing container + pager selector genuinely can't be
made reliable enough for the unified pattern, treat that as a sign the site
needs closer per-page discovery work (step 1 above), not a reason to fall
back to a curated listing list.

---

## Step-by-step: generic harvester

For simple sites, skip to a single harvest phase:

```
scrapy crawl generic_crawl_harvest \
    -a url=https://example.archives.gov/ \
    -a rules_file=data/example/one_off_denies.yml \
    -o data/example/example_harvest.csv
```

Where `one_off_denies.yml` has a `nav_deny: ['/print/', '/user/', '/node/\d']` list.
`extensions`/`rules`/`pagination`/`query_params_allow` default to
`archive_crawler/exclusion_rules/generic_crawl_harvest.yml` unless `-a
source_site=<name>` points at a specific site's own committed file instead;
either way, `rules_file` (default mode: append) overlays on top.

`?page=`/`/page/` links are followed but not recorded as content. Every followed
link also has its query string reduced to just the pagination param, if present —
Scrapy's duplicate-request filter then collapses facet/sort/tracking-decorated
variants of the same page into a single crawl. This does not stop distinct facet
*paths* (e.g. chained `/field_tags/X/field_tags/Y/` segments on faceted-search
sites) from each being crawled once each — block those per-site with a
`nav_deny` entry (e.g. `-a rules_file=... ` with `nav_deny: ['/field_tags/', '/search/']`).

Then scrape using `generic_crawl` or a custom scraper spider:

```
scrapy crawl generic_crawl \
    -a url_file=data/example/example_harvest.csv \
    -a site_id=example \
    -a source_type='Archived White House Websites' \
    -o data/example/example.csv
```

`generic_crawl`'s selectors (`generic_crawl.py`) are a union tuned to the site
templates already seen in this repo, not a universal HTML-content detector. A new
site's first run commonly yields zero items — extend the XPath union or subclass
with site-specific selectors, same as any other new site's scraper.

---

## Naming conventions

**`NavHarvesterMixin` pattern:**

| File | Spider name |
|---|---|
| `<site>.py` | `<site>` |
| Output CSVs | `data/<site>/<site>_harvest-full.csv`, `data/<site>/<site>.csv` (two `FEEDS` from one run) |

One file, one class, one crawl (step 2's discovery-only version and step
4's content-extracting version are the same file, not two).

Use the `source_site` value as `<site>` (e.g. `letsmove.obamawhitehouse`,
`petitions.trumpwhitehouse`). Dots in the source_site become dots in filenames.
