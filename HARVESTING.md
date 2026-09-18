# Harvesting a New Site

This document describes the end-to-end process for adding a new site to the crawl
pipeline. `generic_crawl_harvest`/`generic_crawl` split URL discovery and content
extraction into two separate spiders. The sitemap-based (`SitemapUrlSpiderMixin`)
and `NavHarvesterMixin` patterns each use one spider for both, with content
extraction added once selectors are ready. Either way, discovering the full URL
list before writing (or running) any content-extraction code makes coverage
gaps and unexpected pages visible early, rather than after they turn into data
problems.

Check for a sitemap first (`/sitemap.xml`, `/sitemap_index.xml`, or a `Sitemap:`
directive in `robots.txt`). If one exists, skip everything else in this document,
and use the sitemap harvester below. The remaining sections (choosing a harvester
pattern, the nav harvester, the generic harvester) are all for sites with **no**
sitemap.

---

## Sitemap harvester

If the site has a sitemap, use `sitemap_harvest`, a single-phase, one-size-fits-all
harvester with no site-specific code to write:

```
scrapy crawl sitemap_harvest \
    -a sitemap_url=https://example.archives.gov/sitemap.xml \
    -a source_site=example
```

It fetches the sitemap (or sitemap index, recursing into all sub-sitemaps),
deduplicates URLs case-insensitively, drops non-web assets (PDFs, images, and
similar), and writes a harvest CSV, one `url` column, one row per content page,
without fetching any content pages itself.

Output is automatic, derived from `source_site`: the harvest CSV goes to
`data/example/example_harvest.csv`, and any dropped non-web-extension
URLs go to `data/example/example_harvest-dropped.csv` (this file only gets
written when at least one URL actually gets dropped). This is the one spider
in the project where `-O`/`-o` do not control output at all. Pass
`-a harvest_file=<path>` and, or, `-a dropped_file=<path>` to override either
default explicitly.
Without `source_site`, `harvest_file` becomes required.

Use this spider only to explore a *new* sitemap-based site's URL shape and
resolved sitemap target before writing that site's spider (watch for a
redirect, for example a WordPress/Yoast site's `/sitemap.xml` 301ing to
`/sitemap_index.xml`). Nothing downstream consumes its own harvest CSV
output. The 8 already-onboarded sitemap-based sites (Clinton
CW1–6, Biden, GWBush) never run this spider at all: each has its own
`SITEMAP_URL` hardcoded, and fetches and scrapes in one `scrapy crawl
<name>` run through `SitemapUrlSpiderMixin` (`archive_crawler/spiders/base.py`).
None of them needs a separate content-spider file. See the "Sitemap-Based
Archive Spiders" section in README for a worked example, and its "Warnings column"
section for the `parse_item` shape (`no_body`/`no_title`/`short_body` flag
a row rather than exclude it).

### Creating a new sitemap-based site's spider

Copy an existing sitemap spider (for example, `archive_crawler/spiders/clintonwhitehouse2.py`) and update:
- `name`, `allowed_domains`, `SOURCE_SITE`, `SOURCE_TYPE`
- `SITEMAP_URL`, the resolved sitemap or sitemap-index URL found above
- `custom_settings['FEEDS']`, with two entries: the harvest CSV
  (`data/<SOURCE_SITE>/<SOURCE_SITE>_harvest.csv`, `item_classes:
  [HarvestItem]`, `fields: ['url']`), and the content CSV
  (`data/<SOURCE_SITE>/<SOURCE_SITE>.csv`, `item_classes: [ArchiveItem]`,
  the same `fields` list as every other content spider). Copy the exact
  shape from any existing sitemap-based spider. This is what makes the new
  spider's output automatic, with no `-O` needed to run it.
- Create `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml` for any
  URL-pattern exclusions `start_requests` needs (`rules: [{match, pattern,
  reason}, ...]`). See `www.georgewbush-whitehouse.yml` for an example.
  `start_requests` itself just calls `self._get_exclusion_rules()` and
  `exclusion_rules.match_exclude(url, rules)`. It needs no per-site Python.
- Create `archive_crawler/filter_rules/<SOURCE_SITE>.yml` for
  `scrape_index_pipeline`'s warning-based row filter (`drop_if_all_present:
  [no_body]`, or `[]` for "never drop"). See README's "Warnings Column"
  section for what `no_body`/`no_title`/`short_body` mean.
- CSS selectors in `parse_item`, to match the new site's content structure

All sitemap-based spiders inherit from `SitemapUrlSpiderMixin` (which
itself extends `ArchiveSpiderMixin`, for its content-extraction helpers.
The two stay separate specifically so a `NavHarvesterMixin`-composed spider,
which also extends `ArchiveSpiderMixin`, never inherits sitemap-fetching
behavior it does not use). Between the two, this gives every sitemap-based
spider:
- `start_requests()` / `_parse_sitemap(response)` (`SitemapUrlSpiderMixin`):
  fetches `SITEMAP_URL`, recurses `sitemapindex` entries, drops whatever
  this site's exclusion rules match (and logs each one), and requests the
  rest with the standard callback and HTTP error errback
- `_make_request(url)` (`ArchiveSpiderMixin`): builds a `parse_item`
  request with the standard HTTP error errback
- `_extract_title(response)`: tries h1, then h2, then `<title>`, with HTML entity decoding and normalization
- `_extract_text(response, selector)`: strips NARA banners, nav boilerplate, and invisible Unicode before returning plain text
- `_log_exclusion(url, reason)`: records a sitemap URL rejected before it ever got a harvest row (an extension or `rules:` match during `_parse_sitemap`). This writes to `_exclusions.csv` when the spider closes
- `_log_dropped(url, reason)`: records a URL that already has a harvest row, then got rejected. Causes include a bad response, or a fetch that succeeded but got judged non-content. This writes to `_dropped.csv` when the spider closes — see README's "Exclusion & Dropped Output" section
- `_get_exclusion_rules()`: loads `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`, overlaid with `-a rules_file=<path>` `-a rules_mode=append|replace` when given
- `_get_short_body_threshold()` / `_slug_title(url)`: the `warnings` column's `short_body` threshold (default 30 characters), and the `no_title` fallback title
- `EXTRA_STRIP_SELECTORS` / `EXTRA_STRIP_XPATH`: per-spider hooks for site-specific boilerplate

### Validating output

```bash
# Row count
wc -l data/{source_site}/{source_site}.csv

# Check for empty titles or full_text (should return 0)
python -c "
import csv
with open('data/{source_site}/{source_site}.csv') as f:
    rows = list(csv.DictReader(f))
print('empty title:', sum(1 for r in rows if not r.get('title')))
print('empty full_text:', sum(1 for r in rows if not r.get('full_text')))
print('teaser >200:', sum(1 for r in rows if len(r.get('teaser_text','')) > 200))
"

# URL gap report (harvest vs. output)
python audit_url_gaps.py \
  --harvest data/{source_site}/{source_site}_harvest.csv \
  --output  data/{source_site}/{source_site}.csv \
  --depth 3 --source-site {source_site}
```

This validation applies equally to a `NavHarvesterMixin` site's output.

---

## Choosing a harvester pattern

The following patterns are for sites with no sitemap.

**Use `NavHarvesterMixin`.** This is the recommended pattern for any no-sitemap
site. One spider handles nav link-following, listing pagination-walking (when
step 1 finds a reliable listing container and pager selector), and content
extraction, all in a single pass over each fetched response. See
"Step-by-step: nav harvester" below. Listing detection is optional. A site
with no shared-catalog-widget risk (for example, `open_obama_whitehouse.py`, a
few hundred pages) can skip `LISTING_VIEW_LINK_EXTRACTOR`,
`LISTING_CONTAINER_SELECTOR`, and `LISTING_PAGER_SELECTOR` entirely, and rely on
`DEPTH_LIMIT` plus `rules:` for scope, the same as that one does.

`generic_crawl_harvest`/`generic_crawl` is starter and example tooling, not a
production-ready alternative for a new site. Its selectors target
site templates already seen in this repo, not universal ones, so this
decision tree excludes it. See README's "Running Locally (Development)"
section if you want to use it for local exploration anyway.

---

## Step-by-step: nav harvester

A single spider class, composing `NavHarvesterMixin` and `ArchiveSpiderMixin`
together, runs one full-site discovery crawl. It finds ordinary content and
listing pages in the same pass, walks a newly flagged listing's pagination
automatically the first time it sees that listing's item set, and extracts
that page's title, body, and teaser on the same fetched response. See
[ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the fingerprint mechanism this relies on, including its known
limitations and the discovery you should do before trusting it against a
new site. This is the recommended pattern for any listing-bearing,
no-sitemap site. `letsmove.py` and `obama_whitehouse.py` serve as worked
examples.

Content extraction is optional at first. A class composing only
`NavHarvesterMixin` (no `ArchiveSpiderMixin`, no `_scrape_item` method) is a
pure harvest-only spider, useful for auditing the full URL list before
writing any selectors. Add `ArchiveSpiderMixin` and a `_scrape_item` method
to that same class later (step 4), to start getting content on the very next
run. `_maybe_scrape_item` (in `nav_harvest.py`) extracts content whenever
`_scrape_item` exists on the class, and skips it otherwise.

### Step 1 — Discovery

Inspect the live site to answer these questions before writing any code:

- What are the paginated listing sections (blog, news, press releases, and similar)?
  Look for pagination controls, and note the URL pattern for page 2 and on.
- What CSS selector identifies a content link within a listing row? Check
  more than one listing page if the site has more than one visual template
  for listings (for example, a teaser-card blog archive versus a table-based
  photo/video gallery can use completely different item-link markup, even on
  the same site — `obama_whitehouse.py`'s `_listing_pagination_items` handles
  two such templates).
- What container reliably wraps *both* a listing's item rows and its
  pager or filter controls (for example, Drupal Views' own `.view` wrapper)?
  This is what `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR`
  (see step 2) use, to flag an unknown listing page safely, one container at
  a time when a page carries more than one. Verify it on at least one confirmed
  listing *and* one page you know is not a listing but embeds some other
  single-item view widget. `.views-row` presence alone does not reliably
  signal this (a content page can embed a single-item view, and carry the
  same markup as a real listing. See `NavHarvesterMixin`'s docstring). A
  populated pager or filter block inside the container is the real signal,
  not the container's mere presence.
- What are the top-level nav sections? These become `start_urls` for the nav
  spider. Often the homepage alone is enough (see step 2).
- Are there path prefixes that should stay out of scope regardless
  of phase (for example, a non-English mirror, `/sites/` Drupal assets)? Put
  these in `rules:`, in the new site's
  `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`. A `rules:` entry
  covers both the nav crawl (see `NavHarvesterMixin._apply_exclusion_rules`)
  and the content spider.
- What is the domain? Do any subdomains need handling by separate spiders?

### Step 2 — Nav + listing discovery crawl

Create `archive_crawler/spiders/<site>.py` using `NavHarvesterMixin`. Set
`SOURCE_SITE` (this class will compose `ArchiveSpiderMixin` too, once step 4
adds content extraction, so it needs only one `SOURCE_SITE` and one
exclusion rules file for this site). If step 1 found a reliable
listing-container selector and pager selector, set all
three of `LISTING_VIEW_LINK_EXTRACTOR`, `LISTING_CONTAINER_SELECTOR`, and
`LISTING_PAGER_SELECTOR` (required together), so the crawler can safely
wander into a listing it has never seen before. It flags the page
(`is_listing=True` in the output) instead of excluding it, and does not
follow any link inside a matched container (item links and pager or filter
controls alike), so discovering a huge listing cannot make the crawler fan
out across its full item or pagination range. Instead, the mixin
fingerprints each container's item set (combined with its Drupal
view-id and display-id, when present), and walks its pagination automatically
the first time it sees that combination, fetching every extracted item through
this same crawl. So this one spider's output already forms the complete
harvest, with no separate listing spider or merge step needed. See
[ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the full mechanism and its known limitation.
`LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR` alone are not
enough. An ordinary content page that merely embeds a "related content"
widget can render inside the exact same container with real links but no
pager at all. `LISTING_PAGER_SELECTOR`, which requires an actual populated
pager, is what tells the two apart.

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
            'data/mysite/mysite_harvest.csv': {
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
                           # _apply_exclusion_rules directly, and CrawlSpider's own
                           # Rule-dispatch machinery that would call it is
                           # disabled entirely (see the mixin's
                           # custom_settings) - process_links= here would be
                           # dead configuration.
        ),
    )
```

If you override `custom_settings` in a subclass, it **replaces** the
mixin's dict entirely, rather than merging with it. Keep
`'CRAWLSPIDER_FOLLOW_LINKS': False` in whatever you set. Otherwise
CrawlSpider's own built-in link-following silently re-enables for that
spider (see the comment on `NavHarvesterMixin.custom_settings` in
`nav_harvest.py` for why).

Every crawl starts fresh. No listing or dedup file needs seeding:

```
scrapy crawl mysite \
    -s DEPTH_LIMIT=10 \
    -s DEPTH_PRIORITY=1 \
    -s SCHEDULER_DISK_QUEUE=scrapy.squeues.PickleFifoDiskQueue \
    -s SCHEDULER_MEMORY_QUEUE=scrapy.squeues.FifoMemoryQueue
```

`custom_settings['FEEDS']` already defines the output path, so this needs
no `-O`. Step 4 adds a second `FEEDS` entry (for content) to that same dict,
once `_scrape_item` exists on the class.

The `DEPTH_PRIORITY`/`SCHEDULER_*` flags switch Scrapy's default LIFO
(depth-first) traversal to breadth-first. This matters beyond even
coverage alone. Scrapy's dupefilter is a one-time gate: whichever request for a
URL is first to pass it wins, and *that* request's depth is what gets
recorded, with no correction if a shorter path turns up later. Under DFS this
can wildly overstate a page's true distance from the seed. In one real run, a
direct child of an already-visited page recorded at depth 9, needing only
depth 1, because DFS happened to explore a much longer path to it first. BFS
at `CONCURRENT_REQUESTS_PER_DOMAIN=1` makes recorded depth an exact
shortest-path guarantee. Raising concurrency reopens a narrow version of the
same race (a deeper-layer candidate can fill an idle slot while a
shallower layer's response is still in flight), but that is usually a small,
acceptable error for a discovery-only run, not something to rely on for a
precise claim.

BFS matters only for this initial discovery run, while `DEPTH_LIMIT` is
still under tuning against real depth-exceeded gaps (step 3). Once a site's
`DEPTH_LIMIT` sits comfortably past its longest real pagination chain,
ordering no longer affects completeness, and later runs can drop back to
Scrapy's default DFS scheduler. See README's Obama White House walkthrough
for a site already past this point.

Run this **untimed** (no `CLOSESPIDER_TIMEOUT`), so it actually exhausts the
site rather than stopping mid-traversal. A partial run cannot tell
"genuinely unreachable within `DEPTH_LIMIT`" apart from "just did not get there yet."

### Step 3 — Spot-check listing detections

Filter the harvest CSV for `is_listing=True`, and spot-check them for false
positives. A content page that merely embeds a single-item view can still
carry the same container markup as a real listing, though a populated pager
inside it is a much stronger signal than raw item-row markup alone. This
process needs no promotion step. Every flagged listing's pagination gets walked
automatically the first time its item-set fingerprint appears (step 2). If
fingerprinting is ever confirmed to miss a real duplicate catalog,
add the offending URL to `FORCE_SKIP_LISTING_URLS`, rather than introducing a
curated seed list.

Also check the crawl log for `Ignoring link (depth > N)` entries not already
in the harvest CSV. These are genuine gaps, cut off purely by `DEPTH_LIMIT`,
not dead ends, and may warrant adding their section root as an additional
`start_urls` seed for a follow-up run (only after confirming the gap, not
preemptively).

### Step 4 — Scrape

Add `ArchiveSpiderMixin` to the **same class** from step 2, and give it a
`_scrape_item(self, response)` method. This plays the same role as a
standalone spider's `parse_item`, but `_maybe_scrape_item` (in
`nav_harvest.py`) calls it on the response `parse_nav` already fetched for
discovery, not a second request.
This is one of two ways this repo fuses discovery and content-extraction
into a single spider. The other is `SitemapUrlSpiderMixin`, for
sitemap-based sites (see "Sitemap harvester" above). The two are not
interchangeable (one discovers through nav link-following, the other through a
sitemap), but neither one needs a separate harvest-then-scrape pass.

`_scrape_item` follows the same accumulate-and-continue shape as every
other content spider in this repo. `no_body`/`no_title` do not drop the row
(a real page got fetched, so this flags it instead of hiding it). `short_body`
flags a non-empty body under `SHORT_BODY_THRESHOLD` (default 30 characters,
override through the `SHORT_BODY_THRESHOLD` class attribute or
`-a short_body_threshold=<N>`). A missing title falls back to
`_slug_title(url)` (the last URL path segment, with the extension stripped
and `-`/`_` turned to spaces). See README's "Warnings column"
section (or either of `letsmove.py`/`obama_whitehouse.py`) for the full
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
            'data/mysite/mysite_harvest.csv': {
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

Run it with the same invocation as step 2. `custom_settings['FEEDS']`
defines both output paths directly, so this needs no `-O` (a command-line
`-O`/`-o` would override that whole dict, rather than add to it):

```
scrapy crawl mysite
```

A bare invocation like this always includes content extraction, once
`_scrape_item` exists on the class. To get harvest-only output from a class
that already defines `_scrape_item`, comment it out (or drop
`ArchiveSpiderMixin`) temporarily. `_maybe_scrape_item` no-ops whenever
`_scrape_item` does not exist on the class.

---

## Step-by-step: generic harvester

For simple sites, skip to a single harvest phase:

```
scrapy crawl generic_crawl_harvest \
    -a url=https://example.archives.gov/ \
    -a rules_file=data/example/one_off_denies.yml \
    -o data/example/example_harvest.csv
```

Here, `one_off_denies.yml` has a `rules:` list matching `/print/`, `/user/`, `/node/\d`.
`extensions`/`rules`/`pagination`/`query_params_allow` default to
`archive_crawler/exclusion_rules/generic_crawl_harvest.yml`, unless `-a
source_site=<name>` points at a specific site's own committed file instead.
Either way, `rules_file` (default mode: append) overlays on top.

`?page=`/`/page/` links get followed, but not recorded as content. Every followed
link also has its query string reduced to just the pagination parameter, when present.
Scrapy's duplicate-request filter then collapses facet, sort, and tracking-decorated
variants of the same page into a single crawl. This does not stop distinct facet
*paths* (for example, chained `/field_tags/X/field_tags/Y/` segments on
faceted-search sites) from each getting crawled once each. Block those per-site
with a `rules:` entry (for example, `-a rules_file=... ` matching `/field_tags/`, `/search/`).

Then scrape using `generic_crawl` or a custom scraper spider:

```
scrapy crawl generic_crawl \
    -a url_file=data/example/example_harvest.csv \
    -a site_id=example \
    -a source_type='Archived White House Websites' \
    -o data/example/example.csv
```

`generic_crawl`'s selectors (`generic_crawl.py`) form a union tuned to the site
templates already seen in this repo, not a universal HTML-content detector. A new
site's first run commonly yields zero items. Extend the XPath union, or subclass
with site-specific selectors, the same as for any other new site's scraper.

---

## Naming conventions

**`NavHarvesterMixin` pattern:**

| File | Spider name |
|---|---|
| `<site>.py` | `<site>` |
| Output CSVs | `data/<site>/<site>_harvest.csv`, `data/<site>/<site>.csv` (two `FEEDS` from one run) |

One file, one class, one crawl (step 2's discovery-only version and step
4's content-extracting version are the same file, not two).

Use the `source_site` value as `<site>` (for example, `letsmove.obamawhitehouse`,
`open.obamawhitehouse`). Dots in the source_site become dots in filenames.
