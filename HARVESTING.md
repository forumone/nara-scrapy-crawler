# Harvesting a New Site

This document describes the end-to-end process for adding a new site to the crawl
pipeline. The two-phase approach (harvest URLs first, scrape content second) allows
for auditing the full URL list before any content is fetched, making coverage gaps
and unexpected pages visible before they become data problems.

Check for a sitemap first (`/sitemap.xml`, `/sitemap_index.xml`, or a `Sitemap:`
directive in `robots.txt`) — if one exists, skip everything else in this document
and use the sitemap harvester below. The remaining sections (choosing a harvester
pattern, the split harvester, the generic harvester) are all for sites with **no**
sitemap.

---

## Sitemap harvester

If the site has a sitemap, use `sitemap_harvest` — a single-phase, one-size-fits-all
harvester with no site-specific code to write:

```
scrapy crawl sitemap_harvest \
    -a sitemap_url=https://example.archives.gov/sitemap.xml \
    -O data/example/example_harvest-full.csv
```

It fetches the sitemap (or sitemap index, recursing into all sub-sitemaps),
deduplicates URLs case-insensitively, drops non-web assets (PDFs, images, etc.), and
outputs a harvest CSV — one `url` column, one row per content page — without
fetching any content pages itself. Used by all of Clinton (CW1–6), Biden, and GWBush.

Then write a dedicated content spider using `ArchiveSpiderMixin` (same pattern as
Step 5 in the split-harvester walkthrough below) to scrape from that harvest CSV.
See README's "Sitemap-Based Archive Spiders" section for a worked example against
an existing spider.

---

## Choosing a harvester pattern

The following patterns are for sites with no sitemap.

**Use `generic_crawl_harvest`** for small, simple sites. It follows `?page=`/`/page/`-style
pagination automatically (without recording the listing pages themselves as content —
only the content links found on them), so ordinary paginated listing sections don't
by themselves require the split pattern anymore.

**Use the split harvester pattern** (`*_harvest_list` + `*_harvest_nav`) when a site's
pagination doesn't follow the `?page=`/`/page/` convention (custom offset/cursor
params, JS-driven infinite scroll, etc.), or when listing rows need a specific CSS
selector to identify the real content link rather than generic link-following. The
nav spider alone will miss content behind pagination; the list spider alone will
miss nav-only pages.

If you are not sure, start with site discovery (step 1) and try `generic_crawl_harvest`
first — if the pagination doesn't match the standard convention or content links can't
be reliably distinguished from navigation/facet noise, fall back to the split pattern.

---

## Step-by-step: split harvester

Two orderings are possible. **Nav-first** (recommended default) runs a single
full-site discovery crawl that finds both ordinary content and listing pages
in one pass, then walks only the confirmed listings' pagination afterward.
**List-first** (the older pattern, still valid — see the callout at the end)
curates a small set of known listings up front, harvests their pagination,
and only then nav-crawls the rest of the site while skipping what's already
known. Nav-first needs less upfront knowledge of the site and doesn't require
guessing every listing section in advance; list-first is simpler to reason
about for a site with a small, easily-enumerable set of listings and no
reliable way to detect an unknown one from its markup alone.

### Step 1 — Discovery

Inspect the live site to answer these questions before writing any code:

- What are the paginated listing sections? (blog, news, press releases, etc.)
  Look for pagination controls and note the URL pattern for page 2+.
- What CSS selector identifies a content link within a listing row? Check
  more than one listing page if the site has more than one visual template
  for listings (e.g. a teaser-card blog archive vs. a table-based photo/video
  gallery can use completely different item-link markup even on the same
  site — `obama_whitehouse_harvest_list.py` handles two such templates).
- What container reliably wraps *both* a listing's item rows and its
  pager/filter controls? (e.g. Drupal Views' own `.view` wrapper) This is
  what `LISTING_VIEW_LINK_EXTRACTOR` (nav-first only, see step 2) uses to
  flag an unknown listing page safely. Verify it on at least one confirmed
  listing *and* one page you know isn't a listing but embeds some other
  single-item view widget — `.views-row` presence alone is not reliable for
  this (a content page can embed a single-item view and carry the same
  markup as a real listing; see `NavHarvesterMixin`'s docstring). A populated
  pager/filter block inside the container is the actual signal, not the
  container's mere presence.
- What are the top-level nav sections? These become `start_urls` for the nav
  spider — for nav-first, often just the homepage is enough (see step 2).
- Are there path prefixes that should be universally out of scope regardless
  of phase? (e.g. a non-English mirror, `/sites/` Drupal assets) Put these in
  `rules:` in the new site's `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`
  — nav-time exclusion checks `rules ∪ nav_deny`, so a `rules:` entry alone
  covers both the nav crawl and the content spider; reserve `nav_deny` for an
  exclusion that should hold the nav crawler back without also excluding the
  URL from a content scrape reached some other way (see
  `NavHarvesterMixin._apply_nav_deny`).
- What is the domain? Are there subdomains that should be handled by separate spiders?

### Step 2 — Nav discovery crawl

Create `archive_crawler/spiders/<site>_harvest_nav.py` using `NavHarvesterMixin`.
Set `SOURCE_SITE` to match the content spider's own `SOURCE_SITE` (they share
one `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml` file), and — if step 1
found a reliable listing-container selector and pager selector — set both
`LISTING_VIEW_LINK_EXTRACTOR` and `LISTING_PAGER_SELECTOR` (required
together) so the crawler can safely wander into a listing it's never seen
before: it flags the page (`is_listing=True` in the output) instead of
excluding it, and does not follow any link inside the matched container (item
links and pager/filter controls alike), so discovering a huge listing can't
make the crawler fan out across its full item or pagination range.
`LISTING_VIEW_LINK_EXTRACTOR` alone is not enough — an ordinary content page
that merely embeds a "related content" widget can render inside the exact
same container with real links but no pager at all; `LISTING_PAGER_SELECTOR`
requiring an actual populated pager is what tells the two apart (confirmed:
`restrict_css='.view'` alone false-positived on topic pages embedding a
"related videos" block with zero pagination).

```python
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule
from archive_crawler.spiders.base import NavHarvesterMixin

class MySiteHarvestNavSpider(NavHarvesterMixin, CrawlSpider):
    name = "mysite_harvest_nav"
    allowed_domains = ["example.archives.gov"]
    SOURCE_SITE = 'example'  # matches the content spider's SOURCE_SITE

    # Optional, required together: only set these if step 1 found a
    # reliable listing container AND a pager selector that reliably
    # indicates real pagination (not just any link inside the container).
    LISTING_VIEW_LINK_EXTRACTOR = LinkExtractor(
        restrict_css='.view',
        allow_domains=['example.archives.gov'],
    )
    LISTING_PAGER_SELECTOR = '.pager-current'

    start_urls = [
        "https://example.archives.gov/",
        # A single homepage seed is often enough at a generous DEPTH_LIMIT -
        # add more only if a full (untimed) run still logs genuine
        # depth-exceeded ignores for a section, not preemptively.
    ]

    rules = (
        Rule(
            LinkExtractor(
                allow=r'//example\.archives\.gov/',
                allow_domains=['example.archives.gov'],
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
built-in link-following silently re-enables for that spider (confirmed to
leak both a listing's pager link and its `.view` container's item links
straight past `LISTING_VIEW_LINK_EXTRACTOR` when it does — see the comment
on `NavHarvesterMixin.custom_settings` in `base.py` for the full mechanism).

`listing_file` is still a required argument (`NavHarvesterMixin.__init__`
raises without it) — on a first, nav-first run there's no prior harvest to
seed it with, so point it at an empty CSV (header row only):

```
echo "url" > data/mysite/mysite_empty-listing.csv

scrapy crawl mysite_harvest_nav \
    -a listing_file=data/mysite/mysite_empty-listing.csv \
    -s DEPTH_LIMIT=10 \
    -s DEPTH_PRIORITY=1 \
    -s SCHEDULER_DISK_QUEUE=scrapy.squeues.PickleFifoDiskQueue \
    -s SCHEDULER_MEMORY_QUEUE=scrapy.squeues.FifoMemoryQueue \
    -O data/mysite/mysite_harvest-nav.csv
```

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

Run this **untimed** (no `CLOSESPIDER_TIMEOUT`) so it actually exhausts the
site rather than stopping mid-traversal — a partial run can't distinguish
"genuinely unreachable within `DEPTH_LIMIT`" from "just didn't get there yet."

### Step 3 — Review and promote listing candidates

Filter the nav CSV for `is_listing=True` and spot-check them for false
positives before trusting any of them. Also check the crawl log for
`Ignoring link (depth > 10)` entries not already in any known CSV — these are
genuine gaps cut off purely by `DEPTH_LIMIT`, not dead ends, and may warrant
adding their section root as an additional `start_urls` seed for a follow-up
run (only after confirming the gap, not preemptively).

Confirmed listings get added to `<site>_harvest_list.py`'s `start_urls`
(step 4) — hardcoded directly in the source and pushed, if the site is a
static/frozen archive where the true listing set never changes; a dynamic
`-a seeds_file=<path>` argument only if new listings can genuinely appear
later (e.g. a live site being recrawled periodically).

### Step 4 — Listing pagination walk

Create (or extend) `archive_crawler/spiders/<site>_harvest_list.py`. This is a
plain `scrapy.Spider` that paginates through each confirmed listing and
yields one `{'url': href}` per content link found — handle every listing
template step 1 identified, trying each item-link selector in turn:

```python
import scrapy

class MySiteHarvestListSpider(scrapy.Spider):
    name = "mysite_harvest_list"
    allowed_domains = ["example.archives.gov"]
    start_urls = [
        "https://example.archives.gov/blog/",
        "https://example.archives.gov/news/",
        # ... confirmed listing pages from step 3
    ]

    def parse(self, response):
        links = response.css('.views-row .views-field-title a::attr(href)').getall()
        if not links:
            links = response.css('.views-field-title a::attr(href)').getall()  # 2nd known template
        if not links:
            return

        for href in links:
            yield {'url': response.urljoin(href)}

        # .pager-current's immediately-following sibling <li> holds the
        # forward link across multiple Drupal pager styles (a "Next" link in
        # some templates, a numbered page link in others) - more robust than
        # anchoring on .pager-next, which not every template renders.
        next_page = response.css('.pager-current + li a::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
```

Run it:

```
scrapy crawl mysite_harvest_list -o data/mysite/mysite_harvest-listing.csv
```

Inspect the output before continuing. Verify row count is plausible and
spot-check a sample of URLs to confirm they point to individual content
pages, not listing pages. **This file's rows are content items, not listing
pages** — the listing pages' own URLs live in the nav CSV from step 2,
flagged `is_listing=True`. This is also what `NavHarvesterMixin`'s
`listing_file`/`_listing_urls` dedup set holds on a later, non-first run
(content already known, so the nav crawler shouldn't re-fetch or re-follow
it) — not a registry of listing-page URLs, despite the name. Worth reading
`NavHarvesterMixin`'s docstring and `_is_listing_page`'s before touching
either file; conflating the two is an easy, real mistake to make.

### Step 5 — Merge

```
python merge_harvest.py \
    -o data/mysite/mysite_harvest-full.csv \
    data/mysite/mysite_harvest-nav.csv \
    data/mysite/mysite_harvest-listing.csv
```

Inputs don't need identical columns — the merge is on the union, so the nav
CSV's `url,is_listing,depth` and the listing CSV's `url`-only shape combine
cleanly, with `is_listing`/`depth` left blank for rows that don't have them.

Compare the merged URL count against any existing scrape results. Investigate
unexpectedly large gaps before proceeding. Categories of expected non-matches:

- **In existing but not harvest**: check for listing pages, mangled URLs, or
  genuinely unreachable content (403s, 404s). Only the last category is a real gap.
- **In harvest but not existing**: these are new URLs the previous crawl missed.
  Spot-check a sample to confirm they are real content pages, not noise.

> **List-first alternative.** If step 1 couldn't identify a reliable listing
> container and pager selector, or the site's listings are already fully
> known and small: skip both `LISTING_VIEW_LINK_EXTRACTOR` and
> `LISTING_PAGER_SELECTOR`, run step 4 first against a manually-curated
> set of known listing URLs (no step 3 needed), then run step 2's nav crawl
> second with that step's output as a real, non-empty `listing_file` — the
> nav crawl will skip everything already captured and only needs to cover
> whatever's left. This is the original ordering this document used before
> `LISTING_VIEW_LINK_EXTRACTOR` existed, and still fully supported; it just
> requires knowing every listing section up front, and a shallower
> `DEPTH_LIMIT` (2, escalating to 3 or 4 if spot-checking finds gaps) since
> there's no per-page safety net against fanning out into an unknown listing.

### Step 6 — Scrape

Create `archive_crawler/spiders/<site>.py` using `ArchiveSpiderMixin`. It reads
from `url_file` (the merged harvest CSV) and extracts title, body, and teaser.

```python
import csv
import scrapy
from archive_crawler.items import ArchiveItem
from archive_crawler.spiders.base import ArchiveSpiderMixin

class MySiteSpider(ArchiveSpiderMixin, scrapy.Spider):
    name = "mysite"
    SOURCE_SITE = 'mysite'
    SOURCE_TYPE = 'Archived White House Websites'

    def start_requests(self):
        url_file = getattr(self, 'url_file', None)
        if not url_file:
            raise ValueError("url_file argument is required: -a url_file=data/mysite/mysite_harvest_full.csv")
        with open(url_file, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                yield scrapy.Request(row['url'], callback=self.parse_item)

    def parse_item(self, response):
        body = self._extract_text(response, '#maincontent .content')
        if not body:
            return
        title = response.css('h1').xpath('string(.)').get(default='').strip()
        if not title:
            return
        item = ArchiveItem()
        item['url'] = response.url
        item['title'] = title
        item['full_text'] = body
        item['teaser_text'] = self._teaser(body)
        item['source_site'] = self.SOURCE_SITE
        item['source_type'] = self.SOURCE_TYPE
        yield item
```

Run it:

```
scrapy crawl mysite \
    -a url_file=data/mysite/mysite_harvest-full.csv \
    -o data/mysite/mysite.csv
```

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

`generic_crawl`'s selectors (`crawl_spider.py`) are a union tuned to the site
templates already seen in this repo, not a universal HTML-content detector. A new
site's first run commonly yields zero items — extend the XPath union or subclass
with site-specific selectors, same as any other new site's scraper.

---

## Naming conventions

| File | Spider name |
|---|---|
| `<site>_harvest_list.py` | `<site>_harvest_list` |
| `<site>_harvest_nav.py` | `<site>_harvest_nav` |
| `<site>.py` | `<site>` |
| Output CSVs | `data/<site>/<site>_harvest-listing.csv`, `data/<site>/<site>_harvest-nav.csv`, `data/<site>/<site>_harvest-full.csv`, `data/<site>/<site>.csv` |

Note the CSV naming uses a hyphen before the phase name (`_harvest-listing`,
`_harvest-nav`, `_harvest-full`) while the Python module/spider names use an
underscore (`_harvest_list`, `_harvest_nav`) — a real, intentional
inconsistency already present in every existing site's files, not a typo.

Use the `source_site` value as `<site>` (e.g. `letsmove.obamawhitehouse`,
`petitions.trumpwhitehouse`). Dots in the source_site become dots in filenames.
