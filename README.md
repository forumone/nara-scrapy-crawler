# AWS Serverless Web Crawler for Archived Sites

This project is a containerized **Scrapy** crawler designed to run on **AWS Batch**. It serves as the data collection engine for an aggregated search system.

It is designed to crawl static/archived websites, normalize the data into a strict schema, and output JSON files to **Amazon S3**. An S3 Event Trigger then handles ingestion into **AWS OpenSearch**.

> New to this repo? See [QUICKSTART.md](QUICKSTART.md) to validate your local setup with two of the simplest crawlers before reading further.

## 🏗 Architecture

**Drupal (Admin)** ➔ **AWS SQS** ➔ **AWS Batch (This Repo)** ➔ **S3 Bucket** ➔ **Lambda** ➔ **OpenSearch**

1.  **Trigger:** Drupal sends a message to SQS with a URL and Site ID.
2.  **Compute:** AWS Batch spins up a Docker container (this project).
3.  **Crawl:** Scrapy crawls the site using the `generic_crawl` spider.
4.  **Storage:** JSON results are streamed directly to S3.
5.  **Ingest:** A separate Lambda function detects the new file and pushes it to OpenSearch.

## 🚀 Setup & Installation

### Prerequisites
* Python 3.9+
* Docker
* AWS CLI (configured)

### Local Setup

```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
```

> **Note:** `legacy-cgi` is listed in `requirements.txt` and is required on Python 3.13+, where the `cgi` standard-library module was removed. It is a no-op on earlier Python versions.

---

## 🕷️ Running Locally (Development)

`generic_crawl` is a two-phase spider pair, not a single spider — run both to test locally without spinning up Docker.

It's starter/example tooling, not a production-ready scraper for an arbitrary new site: phase 2's selectors are tuned to the site templates already seen in this repo, not universal. Expect to get zero or few items on a genuinely new site's first run — that means the template needs its own selectors added (or a subclass, see `generic_crawl.py`'s docstring), not that the crawl failed.

**Phase 1** (`generic_crawl_harvest`, a `CrawlSpider`) discovers URLs by following links from a seed URL:

```bash
scrapy crawl generic_crawl_harvest \
  -a url="https://letsmove.obamawhitehouse.archives.gov/" \
  -a rules_file=data/letsmove/one_off_denies.yml \
  -s DEPTH_LIMIT=1 \
  -s CLOSESPIDER_PAGECOUNT=2 \
  -O data/letsmove/letsmove_harvest.csv
```

`-a urls_to_skip=...` is retired — pass `-a rules_file=<path to a YAML file with a nav_deny: [...] list>` instead (optionally `-a rules_mode=replace` to override rather than append to the default). See `archive_crawler/exclusion_rules/generic_crawl_harvest.yml` for the shape, or `-a source_site=<name>` to load a specific site's own committed rules file instead of this spider's generic default.

**Phase 2** (`generic_crawl`, a plain `Spider`) reads that harvest CSV and extracts title/body/teaser from each URL — this is where selector/extraction logic actually runs, so it's the one to point at `-s FEED_URI=stdout://` when debugging cleaning logic:

```bash
scrapy crawl generic_crawl \
  -a url_file=data/letsmove/letsmove_harvest.csv \
  -a site_id="letsmove" \
  -s FEED_URI=stdout:// \
  -s FEED_FORMAT=json \
  -s CLOSESPIDER_PAGECOUNT=2
```

---

## 🏛️ Obama White House Spider

`obamawhitehouse.archives.gov` has no sitemap. `obama_whitehouse.py` is one
spider that does nav-style link-following, listing-pagination-walking, and
content extraction (title/body/teaser) all on the same fetched response, in
a single crawl. (`letsmove.py` follows the identical pattern for
`letsmove.obamawhitehouse.archives.gov`, a much smaller site — same shape,
worth reading if this one feels too large as a first example.)

`LISTING_VIEW_LINK_EXTRACTOR` (scoped to `.view`), `LISTING_CONTAINER_SELECTOR`
(`'.view'`), and `LISTING_PAGER_SELECTOR` (`'.pager-current'`), required
together, let the crawler safely wander into a listing page it's never seen
before: it flags the page (`is_listing=True`) instead of excluding it, and
never follows any link inside a matched container. All three hooks are
required together — `.view` presence alone false-positives on ordinary topic
pages that merely embed a "related videos" widget with real links but no
actual pagination; requiring a populated pager is what tells a real listing
apart from one of those.

Which listings actually get their pagination walked is fully automatic, not
curated: `NavHarvesterMixin` fingerprints each flagged listing's extracted
item-URL set the first time it's seen and walks its pagination only on that
first encounter — this is what stops every
`/photos-and-video/{video,photogallery}/*` permalink's byte-identical
sitewide catalog widget from being re-walked from thousands of different
entry points. See
[ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the full mechanism, its known limitations, and the `FORCE_SKIP_LISTING_URLS`/
`LISTING_MAX_PAGES` escape hatches, and `NavHarvesterMixin`'s own docstring
(`archive_crawler/spiders/nav_harvest.py`) for the mixin's API.

All harvester and content CSV files are stored under `data/{source_site}/` subdirectories (the root `data/` is git-tracked via `data/.gitkeep`; `.csv` files are gitignored).

### Step 1: Harvest + scrape

Crawls the whole site starting from the homepage, recording every page along
with an `is_listing` flag and its `depth`, automatically walking each
newly-discovered listing's own pagination inline, and extracting
title/body/teaser from every non-listing page on the same response — one
crawl, two output files via `custom_settings['FEEDS']`. Every crawl starts
fresh — there's no listing/dedup file to seed:

```bash
scrapy crawl obama_whitehouse
```

No `-O`/`-o` needed (or wanted — either would override the two-feed `FEEDS`
dict already set in `custom_settings` rather than adding to it); the harvest
and content CSVs both come from `custom_settings['FEEDS']`, at
`data/www.obamawhitehouse/www.obamawhitehouse_harvest.csv` and
`data/www.obamawhitehouse/www.obamawhitehouse.csv` respectively.

Run this **untimed** (no `CLOSESPIDER_TIMEOUT`) so it actually exhausts the
site rather than stopping mid-traversal. Default scheduler (LIFO/DFS) is
fine here — this site's `DEPTH_LIMIT` is already tuned high enough that
ordering doesn't matter for completeness. See HARVESTING.md's nav-harvester
step 2 for when BFS actually matters vs. not.

Even at the default `DOWNLOAD_DELAY=0.25`, a full crawl takes a long time — run it on
a remote server, not a local machine; see "Recommended run settings" below
for throttling overrides. `_scrape_item` includes a `#video-info .caption`
fallback selector specifically for `/photos-and-video/video/*` gallery pages,
which otherwise extract zero body text under the standard selectors despite
often having a real, substantive caption — no boilerplate (date/duration/
download-link lines also present in that block) is stripped from it, per
this project's general preference for flagging over silent text-stripping.

### Step 2: Spot-check listing detections (as needed)

Filter the harvest CSV for `is_listing=True` rows and spot-check them for
false positives — a content page that merely embeds a single-item view can
still carry the same `.view` wrapper as a real listing, though a populated
pager block inside it is a much stronger signal than raw `.views-row`
presence alone. No promotion step needed: every flagged listing's pagination
is walked automatically the first time its item-set fingerprint is seen (see
above). If fingerprinting is ever confirmed to have missed a real duplicate
catalog on this site, add the offending URL to `FORCE_SKIP_LISTING_URLS`
rather than re-introducing a curated seed list.

### Harvest-only mode

A class composing `NavHarvesterMixin` without `ArchiveSpiderMixin`/
`_scrape_item` is a pure harvest-only spider by construction —
`_maybe_scrape_item` (`nav_harvest.py`) only extracts content when `_scrape_item`
exists on the class. `obama_whitehouse.py` defines `_scrape_item`, so it
always extracts content; getting harvest-only output from it would mean a
temporary variant with that method removed.

---

## 🗺 Sitemap Harvester

`sitemap_harvest` is a generic, one-size-fits-all sitemap URL harvester. It fetches a sitemap (or sitemap index), recurses into all sub-sitemaps, deduplicates URLs case-insensitively, drops non-web assets (PDFs, images, etc.), and outputs a harvest CSV without fetching any content pages.

```bash
scrapy crawl sitemap_harvest \
  -a sitemap_url=https://example.archives.gov/sitemap.xml \
  -a source_site=example
```

Output is automatic, derived from `source_site`: the harvest CSV (one `url` column, one row per content page discovered in the sitemap) is written to `data/example/example_harvest.csv`. Any non-web-extension URLs dropped during the harvest (PDFs, images, etc.) are written to `data/example/example_harvest-dropped.csv` — a `url`/`reason` CSV, same shape as the content spiders' exclusions CSV — but only if at least one URL was actually dropped.

This is the one spider in the project where `-O`/`-o` do **not** control output. Pass `-a harvest_file=<path>` and/or `-a dropped_file=<path>` to override either derived default explicitly. Without `source_site`, `harvest_file` becomes required (there's no site identity to derive a path from), and dropped URLs are only summarized as a count in the crawl log unless `dropped_file` is also passed explicitly.

---

## 🏛️ Sitemap-Based Archive Spiders

The Clinton (CW1–6), Biden, and GWBush whitehouse spiders discover their own URLs directly from each site's committed sitemap and scrape content in the same run — one command, no harvest CSV to hand off between steps:

```bash
scrapy crawl clintonwhitehouse2
```

All spiders inherit from `SitemapUrlSpiderMixin` (see `archive_crawler/spiders/base.py`), which extends `ArchiveSpiderMixin` with a `start_requests` that fetches the spider's own `SITEMAP_URL` class attribute, recurses `sitemapindex` entries the same way `sitemap_harvest` does, applies the site's exclusion rules once per URL, and yields a `parse_item` request for every surviving URL — plus shared extraction logic, exclusion tracking, and HTTP error handling from `ArchiveSpiderMixin`.

Output is automatic — this writes `data/clintonwhitehouse2/clintonwhitehouse2.csv` (the scraped content) and `data/clintonwhitehouse2/clintonwhitehouse2_harvest.csv` (one `url` column, every URL the sitemap yielded that wasn't excluded before being requested), both derived from the spider's own `SOURCE_SITE` (`custom_settings['FEEDS']`, same two-entry shape `obama_whitehouse.py`/`trump_petitions.py` use). Don't pass `-O`/`-o` here — it replaces that two-entry `FEEDS` wholesale rather than adding to it, silently losing the harvest CSV and corrupting the content CSV's own shape (see ARCHITECTURE.md's "Never pass `-O`/`-o` to a multi-`FEEDS`-entry spider").

Replace `clintonwhitehouse2` with any of: `clintonwhitehouse1`, `clintonwhitehouse3`, `clintonwhitehouse4`, `clintonwhitehouse5`, `clintonwhitehouse6`, `bidenwhitehouse`, `georgewbush_whitehouse`.

`sitemap_harvest` (see "Sitemap Harvester" above) is not part of running any of these 8 sites — it remains only for exploring a *new* sitemap-based site's URL shape before writing that site's spider (see "Adding a New Site" below).

### Pre-filtering large sitemaps

Some archives' sitemaps list large numbers of non-content URLs (print-friendly variants, image gallery wrappers, etc.). Each spider's `start_requests` filters these out at request-generation time (per `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`) and records them in the exclusions CSV.

### Warnings column

`no_body`/`no_title`/`short_body` are **not** exclusions — a real page was
fetched, so it's included in the main output CSV, flagged via the
`warnings` column (comma-separated if more than one applies) instead of
being dropped:

| Warning | Meaning |
|---|---|
| `no_body` | Body selector(s) returned empty text. `full_text`/`teaser_text` are empty strings; `title` still extracted normally if present. |
| `short_body` | Body extracted fine but is under `SHORT_BODY_THRESHOLD` (default 30 chars) — override per-spider (class attribute) or per-run (`-a short_body_threshold=<N>`). |
| `no_title` | No title could be extracted. `title` falls back to `_slug_title(url)` — last URL path segment, extension stripped, `-`/`_` → spaces, no title-casing (e.g. `pp99-1.html` → `pp99 1`). This is a synthesized, not authored, title; the `warnings` column is what signals that. |

### Exclusion output

Each scrape spider automatically writes a `{source_site}_exclusions.csv` alongside the output CSV when the spider closes, no `-O`/`-a` needed — pass `-a exclusions_file=<path>` to override the derived default. Each row contains the skipped URL and a typed reason. Unlike the warnings above, these rows never appear in the main output CSV at all — most reasons mean there was no successfully-fetched, parseable page behind them; a few (like `search_listing_page` below) mean the page fetched fine but was judged non-content at scrape time, and are logged explicitly for the same reason: harvest CSV rows should always be accounted for by either the content CSV or the exclusions CSV, never neither.

| Reason | Description |
|---|---|
| `url_pattern:/foo/` | URL matched a known non-content path prefix |
| `extension:<ext>` | Sitemap-based spiders (CW1–6, Biden, GWBush) only: URL failed the site's extension allowlist (e.g. a PDF or image listed in the sitemap) - dropped before it's ever added to the harvest CSV, at the same `_parse_sitemap` pass that applies `rules:`/`nav_deny`, unlike `sitemap_harvest`'s standalone `_harvest-dropped.csv` (a separate file, not used by these 8 sites) |
| `frameset` | Page is a frameset with no extractable content |
| `non_text_response` | Response body isn't text (e.g. a binary file served from an extension-less URL a link-following crawl swept up) |
| `http_404` | HTTP 404 response |
| `http_3xx` | Redirect not followed (redirects are disabled globally) |
| `http_5xx` | Server error |
| `network_error:<type>` | Connection-level failure |
| `search_listing_page` | `open_obama_whitehouse.py`-specific: a `/search`/`/search/type/*` pagination page - fetched and followed for dataset-link discovery, but not a content page itself |
| `pagination_listing_page` | `PetitionsSpiderMixin`-specific (`obama_petitions.py`/`trump_petitions.py`): a root or `/responses` pagination page (`?page=N`) - fetched and followed for petition-link discovery, but not a content page itself |

### URL gap analysis

`audit_url_gaps.py` compares the harvest CSV against the output CSV and groups unaccounted-for URLs by path prefix:

```bash
python audit_url_gaps.py \
  --harvest data/clintonwhitehouse2/clintonwhitehouse2_harvest.csv \
  --output  data/clintonwhitehouse2/clintonwhitehouse2.csv \
  --depth 3 \
  --source-site clintonwhitehouse2
```

Use `--depth 0` to report only the total count without path grouping.

### Recommended run settings

Large archives (CW4–6, GWBush) are best run on a remote server. Override the default throttling with Scrapy's `-s` flag, not bare environment variables — `settings.py` doesn't read `DOWNLOAD_DELAY`/`CONCURRENT_REQUESTS*` from the environment (only `FEED_URI`, `CLOSESPIDER_PAGECOUNT`, and `DEPTH_LIMIT` are), so prefixing the command with `DOWNLOAD_DELAY=0.15 ...` silently has no effect and the crawl runs at the settings.py defaults (`CONCURRENT_REQUESTS_PER_DOMAIN=4`, `DOWNLOAD_DELAY=0.25`).

The right override on the remote server depends on how many crawls are running there *concurrently*, since the shared constraint is combined outbound load, not any single crawl's own politeness:

| concurrent crawls | `DOWNLOAD_DELAY` | `CONCURRENT_REQUESTS_PER_DOMAIN` |
|---|---|---|
| 1 | 0.12 | 10 |
| 2 | 0.15 | 8 |
| 3 | 0.2 | 6 |
| 4–5 | 0.25 | 4 (matches the local default — no override needed) |
| 6–7 | 0.5 | 2 |
| 8+ | 1 | 1 |

```bash
scrapy crawl georgewbush_whitehouse \
  -s DOWNLOAD_DELAY=0.12 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=10
```

To launch on the remote server itself, SSH in and background the crawl with `nohup`/`disown` so it survives disconnect, pointing `--logfile` at a path under that site's `data/{site}/` directory to monitor progress:

```bash
ssh user@example-remote-host \
  "cd /home/scrapy/nara-scrapy-crawler && \
   nohup scrapy crawl obama_whitehouse \
     -s DOWNLOAD_DELAY=0.12 \
     -s CONCURRENT_REQUESTS_PER_DOMAIN=10 \
     --logfile=data/www.obamawhitehouse/obama_whitehouse-20261231.log \
     > /dev/null 2>&1 & disown"
```

Launch only one crawl per SSH invocation — chaining several backgrounded launches together in a single call is unreliable and can silently drop some of them. The SSH command itself may hang past a client-side timeout until the entire remote process tree (including the disowned job) exits; that's expected, not a stuck connection, and its eventual return is a reliable signal the crawl actually finished.

Before raising throttling further, check the target domain's `robots.txt` for a `Crawl-delay` directive — `ROBOTSTXT_OBEY = False` means Scrapy won't enforce it automatically, so it's easy to run faster than the site operator has asked for without noticing.

`settings.py` also sets `MEMUSAGE_LIMIT_MB=8192` (on the assumption these run on a resource-rich remote server): if a crawl's memory footprint exceeds that (e.g. a crawler trap on a faceted-search or listing-heavy site generates unbounded unique URLs), Scrapy closes the spider gracefully and flushes the feed export, rather than the OS OOM-killing the process and losing all buffered output. Override per-run with `-s MEMUSAGE_LIMIT_MB=N` (e.g. a lower value for local dev testing).

---

## 🗂 CSV Naming Convention

All harvester and content output files follow a consistent naming scheme. Every spider except `generic_crawl`/`generic_crawl_harvest` (one-off exploratory tools with no fixed site identity, see "Running Locally" above — the only two spiders that still require `-O`/`-o` for any output at all) writes to its own path automatically. Don't pass `-O <path>` to any of the 14 in-scope content spiders to redirect their output — every one of them has a two-entry `custom_settings['FEEDS']` (harvest + content), and Scrapy's CLI setting replaces that dict wholesale rather than adding to it, silently dropping the harvest CSV and corrupting the content CSV's own shape (see ARCHITECTURE.md). Use `-a exclusions_file=<path>` for the exclusions CSV, and — for `sitemap_harvest` specifically, where `-O` doesn't apply at all — `-a harvest_file=<path>`/`-a dropped_file=<path>`.

| File | Contents |
|---|---|
| `data/{source_site}/{source_site}_harvest.csv` | One of two automatic `FEEDS` outputs from the same run — the surviving URL list, for both sitemap-based spiders (CW1–6, Biden, GWBush) and `NavHarvesterMixin` sites that also extract content (e.g. `obama_whitehouse.py`, `letsmove.py`) |
| `data/{source_site}/{source_site}.csv` | Final content output (includes a `warnings` column — see "Warnings column" above) |
| `data/{source_site}/{source_site}_exclusions.csv` | Skipped URLs with typed reasons (written on spider close) |
| `data/{source_site}/{source_site}-errors-{timestamp}.log` | Scrapy ERROR-level log (written by `ErrorFileLogger` extension) |

Test subsets append `-test`: `{source_site}_harvest-test.csv`, `{source_site}-test.csv`.

`{source_site}` matches the `SOURCE_SITE` value in the spider (e.g., `www.obamawhitehouse`, `clintonwhitehouse2`).

---

## ➕ Adding a New Site

### Choosing a harvester type

- **Sitemap available?** Use `sitemap_harvest` — pass the sitemap URL and `source_site`; output (`{source_site}_harvest.csv`) is automatic.
- **No sitemap?** Use the unified `NavHarvesterMixin` pattern described in detail in `HARVESTING.md`, worked example against Obama WH above.

To check whether a site has a sitemap, try `{base_url}/sitemap.xml` and `{base_url}/sitemap_index.xml`.

### Discovery before writing code

1. Identify listing pages (paginated archives of content — look for `.views-row` or similar list containers). Check more than one listing template if the site has more than one visual shape for listings.
2. Identify the container that wraps *both* a listing's item rows and its pager/filter controls (e.g. Drupal Views' `.view` wrapper), and a selector that only matches when a real pager is present (e.g. `.pager-current`) — a nav spider's optional `LISTING_VIEW_LINK_EXTRACTOR` + `LISTING_CONTAINER_SELECTOR` + `LISTING_PAGER_SELECTOR` (required together) use these to safely flag an unknown listing page instead of needing to know about it in advance, one container at a time if a page carries more than one. Verify on a confirmed listing and a content page that merely embeds a single-item view or a "related content" widget — `.views-row`/`.view` presence alone isn't a reliable signal (both false-positive on embedded widgets that carry the same markup but no pagination), a populated pager is.
3. Identify nav entry points (top-level pages reachable from navigation that aren't on any listing) — often just the homepage is enough at a generous `DEPTH_LIMIT`.
4. Identify content selectors (the CSS selectors for body text and title on content pages).

### Creating a no-sitemap harvester

Always one spider (`NavHarvesterMixin` + `ArchiveSpiderMixin` +
`CrawlSpider`) doing nav-style link-following and content extraction on
the same fetched response - no separate harvest pass. Two variants,
depending on whether the site has a real listing-fan-out risk:

- **With listing-fingerprint dedup** — for a site where the same
  paginated listing (a "browse all videos" widget, a "recent posts"
  block) is embedded on many distinct pages; without dedup, each embed's
  pagination would be walked independently. Copy
  `archive_crawler/spiders/letsmove.py` (smaller, simpler starting point)
  or `archive_crawler/spiders/obama_whitehouse.py` (larger site, multiple
  listing templates), update `name`, `allowed_domains`, `SOURCE_SITE`,
  `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR`/
  `LISTING_PAGER_SELECTOR`, implement `_listing_pagination_items`/
  `_listing_pagination_next_url` (each takes a single container Selector,
  not the full response), and write `_scrape_item` for the new site's
  content selectors (see `HARVESTING.md`'s nav-harvester walkthrough, step
  4, for the full shape including the `warnings` column). Remember to raise
  `DEPTH_LIMIT` well past whatever the longest expected pagination chain is
  (see either spider's own `custom_settings` comment for why).
- **Without dedup (simpler default when no fan-out risk is evident)** —
  leave `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR`/
  `LISTING_PAGER_SELECTOR` unset (the mixin's own default) and rely on
  `DEPTH_LIMIT` + `nav_deny` for scope instead. Copy
  `archive_crawler/spiders/open_obama_whitehouse.py` or
  `archive_crawler/spiders/obama_petitions.py`/`trump_petitions.py`.
  Watch specifically for facet/filter links (a site's own exposed-filter
  or faceted-search UI) getting followed like ordinary content links,
  since there's no container-pooling here to incidentally suppress them -
  `exclusion_rules/open.obamawhitehouse.yml` has a worked example of the
  nav_deny patterns this needed (both a path-based and a query-string-based
  facet convention).
- **List-first (two spiders)** — considered and rejected, not a supported
  fallback. See `HARVESTING.md`'s "List-first split harvester" section for
  why.

### Creating a sitemap-based content spider

First confirm the sitemap URL and shape with `sitemap_harvest` (see
"Sitemap Harvester" above) — this is exploratory only, to find the
resolved sitemap target (watch for a redirect, e.g. a WordPress/Yoast
site's `/sitemap.xml` 301ing to `/sitemap_index.xml` — `SITEMAP_URL` needs
the resolved target, since `REDIRECT_ENABLED` stays `False` project-wide)
and sanity-check the URL count; its own harvest CSV output isn't used by
the spider you're about to write.

Copy an existing sitemap spider (e.g., `archive_crawler/spiders/clintonwhitehouse2.py`) and update:
- `name`, `allowed_domains`, `SOURCE_SITE`, `SOURCE_TYPE`
- `SITEMAP_URL` — the resolved sitemap/sitemap-index URL found above
- `custom_settings['FEEDS']` — two entries, the harvest CSV
  (`data/<SOURCE_SITE>/<SOURCE_SITE>_harvest.csv`, `item_classes:
  [HarvestItem]`, `fields: ['url']`) and the content CSV
  (`data/<SOURCE_SITE>/<SOURCE_SITE>.csv`, `item_classes: [ArchiveItem]`,
  the same `fields` list as every other content spider) — copy the exact
  shape from any existing sitemap-based spider. This is what makes the new
  spider's output automatic — no `-O` needed to run it.
- Create `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml` for any
  URL-pattern exclusions `start_requests` needs (`rules: [{match, pattern,
  reason}, ...]`) — see `www.georgewbush-whitehouse.yml` for an example.
  `start_requests` itself just calls `self._get_exclusion_rules()` and
  `exclusion_rules.match_exclude(url, rules)`; no per-site Python needed.
- CSS selectors in `parse_item` to match the new site's content structure

All sitemap-based spiders inherit from `SitemapUrlSpiderMixin` (which
itself extends `ArchiveSpiderMixin`, for its content-extraction helpers -
kept separate specifically so a `NavHarvesterMixin`-composed spider, which
also extends `ArchiveSpiderMixin`, never inherits sitemap-fetching behavior
it doesn't use). Between the two, this gives every sitemap-based spider:
- `start_requests()` / `_parse_sitemap(response)` (`SitemapUrlSpiderMixin`)
  — fetches `SITEMAP_URL`, recurses `sitemapindex` entries, drops whatever
  this site's exclusion rules match (logging each), and requests the rest
  with the standard callback and HTTP error errback
- `_make_request(url)` (`ArchiveSpiderMixin`) — builds a `parse_item`
  request with the standard HTTP error errback
- `_extract_title(response)` — h1 → h2 → `<title>` with HTML entity decoding and normalisation
- `_extract_text(response, selector)` — strips NARA banners, nav boilerplate, and invisible Unicode before returning plain text
- `_log_exclusion(url, reason)` — records a skipped URL; written to `_exclusions.csv` on spider close
- `_get_exclusion_rules()` — loads `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`, overlaid with `-a rules_file=<path>` `-a rules_mode=append|replace` if given
- `_get_short_body_threshold()` / `_slug_title(url)` — the `warnings` column's `short_body` threshold (default 30 chars, see "Warnings column" above) and `no_title` fallback title
- `EXTRA_STRIP_SELECTORS` / `EXTRA_STRIP_XPATH` — per-spider hooks for site-specific boilerplate

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

---

## 🔎 Indexing Pipeline

`scrape_index_pipeline` takes a site's content CSV through validation,
per-site warning-based row filtering, CSV→JSONL conversion, and (once
wired up) an OpenSearch push. Three subcommands:

```bash
# Validate/filter/convert/push an existing CSV, no crawl
./scrape_index_pipeline index clintonwhitehouse1
./scrape_index_pipeline index --all

# Run the spider only - scrapy crawl <site>, nothing else
./scrape_index_pipeline crawl clintonwhitehouse1
./scrape_index_pipeline crawl --all

# Crawl the site first, then do everything index does
./scrape_index_pipeline crawl-and-index clintonwhitehouse1
./scrape_index_pipeline crawl-and-index --all
```

`<site>` is either a spider name (`bidenwhitehouse`) or a `source_site`
(`www.bidenwhitehouse`) — see `archive_crawler/pipeline/registry.py`.
`index` is the primary path: per "CSVs are frozen source of truth"
(`data/8-03/`), re-invoking a crawl is the exception, not the default
action. Run from the repo root — relative `data/` paths assume that `cwd`.

### Overrides

- `index --csv <path>` — read a different CSV than the site's own
  `data/<site>/<site>.csv` (e.g. a test file, or an arbitrary location).
  `index`-only: `crawl`/`crawl-and-index` never accept a CSV path
  override, since that would mean passing `-O` to the spider, which
  silently corrupts output on every one of these spiders (all 14 have a
  two-entry `FEEDS`) — see ARCHITECTURE.md's "Never pass `-O`/`-o` to a
  multi-`FEEDS`-entry spider". The crawl step always writes to its
  default path; only the *converted JSONL* is redirectable afterward.
- `index`/`crawl-and-index --jsonl <path>` — write the converted JSONL
  somewhere other than alongside the CSV (default: same directory, same
  basename, `.jsonl` extension). Pure file I/O on our own output, not a
  Scrapy setting, so always safe to redirect.
- `crawl`/`crawl-and-index --download-delay <seconds>` (0.1–2) and
  `--concurrent-requests-per-domain <N>` (1–20) — override
  `settings.py`'s defaults (0.25s / 4) for that one run, same as passing
  `-s DOWNLOAD_DELAY=`/`-s CONCURRENT_REQUESTS_PER_DOMAIN=` directly to
  `scrapy crawl`. See "Recommended run settings" above for what values
  make sense at different concurrent-crawl counts.
- `crawl`/`crawl-and-index --logfile <path>` — write the *entire* crawl
  log there instead of stdout/stderr (Scrapy's own `_get_handler()`
  picks a file handler or a console handler, never both, so this is an
  either/or). Default (no `--logfile`): the full log prints live to the
  terminal, same as running `scrapy crawl` directly. Either way,
  `ErrorFileLogger` keeps writing ERROR-level messages to
  `data/<site>/<site>-errors-<timestamp>.log` — that's a second,
  independent handler this doesn't touch. When `--logfile` is given and
  stdout is a real terminal, a spinner (`-\|/`) plus an elapsed-seconds
  counter fills the gap the diverted log would otherwise leave blank —
  ticks on its own thread, independent of the crawl subprocess, so
  nothing the crawl does can stall or slow it down. Silently skipped
  (falls back to a plain wait) when stdout isn't a terminal — a Docker/
  automated invocation's logs never fill up with carriage-return noise.
- `index`/`crawl-and-index --filter-rules-file <path>` (optionally
  `--filter-rules-mode append|replace`, default `append`) — overlay a
  one-off override on top of the site's committed
  `archive_crawler/filter_rules/<site>.yml`, same shape as
  `exclusion_rules.py`'s own `-a rules_file=`/`-a rules_mode=` for
  spiders. See "Pipeline stages" below for what that file controls.
- `--csv`/`--jsonl`/`--logfile`/`--filter-rules-file` cannot be combined
  with `--all` — a single path can't apply to 14 different sites in one
  invocation. `--download-delay`/`--concurrent-requests-per-domain`
  *can* be combined with `--all` — the same throttle value applies
  uniformly across every site in the loop.

`scrape_index_pipeline_interactive` prompts for site and mode instead of
requiring them as CLI args, then confirms and execs the equivalent
`scrape_index_pipeline` command — same division of labor as the old
`run_crawl_interactive.sh` → `run_crawl.sh` pattern this replaces.

### Pipeline stages (`archive_crawler/pipeline/`)

- **`registry.py`** — `list_sites()` enumerates every content spider via
  `scrapy.spiderloader.SpiderLoader`, keyed by `source_site` (excludes
  `generic_crawl`/`generic_crawl_harvest`/`sitemap_harvest`, which have no
  fixed site identity). `resolve(site_arg)` looks a site up by either
  spider name or `source_site`.
- **`validate.py`** — every `source_site` value present must be a known
  site, and `full_text`/`teaser_text` are checked against a bare-URL regex
  to catch a column swap. Raises `ValidationError` listing every problem
  found, not just the first. Narrower than
  `~/git/nara/scripts/validate-opensearch-csv.py` (invisible-unicode,
  HTML-tag, HTML-entity, missing-space, "Continue reading" checks) — that
  script audits CSVs already pulled back out of the live index; this one
  only gates whether a row is indexed at all.
- **`filter_rows.py`** — reads `archive_crawler/filter_rules/<source_site>.yml`
  (`drop_if_all_present: [no_body]`, or `[]` for "never drop") to decide
  which `warnings` labels (see "Warnings column" above) drop a row before
  conversion. A row is dropped only when its warning set is a *superset*
  of that list (a two-label entry requires both labels present, not
  either). A `source_site` with no committed file raises rather than
  silently defaulting either way. `--filter-rules-file`/
  `--filter-rules-mode` (see "Overrides" above) overlay a per-run
  override on the committed file without editing it, same shape as
  `exclusion_rules.py`'s own overlay for spiders.
- **`convert.py`** — CSV row → `archive_content_v2` document field mapping
  (`source_type` → `source_type_id` is the one renamed field; `warnings`
  is dropped, not on the live mapping). `id`/`document_type`/`source`/
  `changed` aren't populated — no document from any of the 14 archive
  sites exists in the live index yet to reference their shape.
- **`reconcile.py`** — **stub.** Logs a dry-run summary (row count,
  `source_site`, destination) and makes no AWS/network call. Blocked on:
  whether `nara-opensearch-lambda` supports delete-then-upsert/reconcile
  or only blind bulk-upsert; where it watches in S3; what AWS access this
  utility needs; and what should populate `id`/`document_type`/`source`/
  `changed`. None of the other stages depend on these answers.

---

## 📂 Project Structure

`spiders/generic_crawl_harvest.py`: Phase 1 of the generic two-phase spider pair. Uses CrawlSpider and LinkExtractors to walk the site from a seed URL and write a URL-per-row CSV. Dynamically accepts `url`, `source_site`, `rules_file`, and `rules_mode`.

`spiders/generic_crawl.py`: Phase 2 (spider name `generic_crawl`). Reads the phase-1 harvest CSV and extracts title/body/teaser from each URL. Dynamically accepts `url_file`, `site_id`, and `source_type`.

`spiders/base.py`: `ArchiveSpiderMixin` — shared extraction and boilerplate stripping for all archive content spiders. Every subclass that doesn't set its own `custom_settings` gets an automatic `FEEDS` entry derived from `SOURCE_SITE`. `SitemapUrlSpiderMixin` (extends `ArchiveSpiderMixin`) adds `start_requests` for the sitemap-based spiders (CW1-6, Biden, GWBush): fetches the spider's own `SITEMAP_URL`, recurses `sitemapindex` entries, and yields a `parse_item` request for every surviving URL directly - no separate harvest-then-scrape pass. Kept off `ArchiveSpiderMixin` itself so a NavHarvesterMixin-composed spider (which also extends `ArchiveSpiderMixin`, for its content-extraction helpers) falls through to `CrawlSpider`/`Spider`'s own `start_requests` without any MRO override needed. `PetitionsSpiderMixin` (the obama_petitions/trump_petitions template) and `omb_paygo_title` also live here.

`spiders/nav_harvest.py`: `NavHarvesterMixin` — shared nav link-following and listing-fingerprint pagination-walking; when a class composes both this and `ArchiveSpiderMixin` and defines `_scrape_item`, `_maybe_scrape_item` also extracts content on that same fetched response, with no second fetch.

`spiders/exclusion_logging.py`: `ExclusionLoggingMixin` — shared exclusion-rule access and logging (writes `{SOURCE_SITE}_exclusions.csv` automatically on spider close, overridable with `-a exclusions_file=<path>`) composed by both mixins above.

`spiders/sitemap_harvest.py`: Generic, one-size-fits-all sitemap URL harvester, used by all sitemap-based sites (CW1–6, Biden, GWBush). Accepts `-a sitemap_url=`, `-a source_site=`, and optional `-a rules_file=`/`-a rules_mode=`. Output paths (`{source_site}_harvest.csv`, `{source_site}_harvest-dropped.csv`) are automatic, derived from `source_site`, and overridable with `-a harvest_file=`/`-a dropped_file=` — the one spider in the project where `-O`/`-o` don't control output at all.

`exclusion_rules.py`: Loads per-domain URL exclusion rules from `exclusion_rules/<SOURCE_SITE>.yml` (extension allow/deny list, `contains`/`regex` URL-pattern rules, nav-crawl deny patterns, generic-crawl pagination/query-param config). Every harvest-capable spider accepts `-a rules_file=<path>` and `-a rules_mode=append|replace` to overlay a per-run override on the committed file without editing it.

`exclusion_rules/`: One committed YAML file per domain (see `exclusion_rules.py` above). New sites should get one even if empty, so `-a rules_file`/`-a rules_mode` always has a base to overlay onto.

`filter_rules/`: One committed YAML file per `source_site` (`drop_if_all_present: [...]`, see `pipeline/filter_rows.py` under "Indexing Pipeline" above) — the index-time counterpart to `exclusion_rules/`, kept in its own directory since it's a different concern (warning-based row filtering) consumed by a different tool (`scrape_index_pipeline`, not the spiders).

`items.py`: `ArchiveItem` — the strict content schema (URL, Title, Full Text, Teaser, Source Site, Source Type, Warnings). `HarvestItem` — the URL/is_listing/depth schema yielded by every `NavHarvesterMixin` spider's discovery pass and every `SitemapUrlSpiderMixin` spider's sitemap-parse pass (only `url` is populated/exported for the latter — `is_listing`/`depth` are nav-crawl-specific).

`extensions/error_log.py`: `ErrorFileLogger` — mirrors Scrapy ERROR-level log output to a per-run file alongside the output CSV.

`audit_url_gaps.py`: Post-hoc URL gap analysis tool.

`pipeline/`: `scrape_index_pipeline`'s modules — see "Indexing pipeline" below.

`scrape_index_pipeline` / `scrape_index_pipeline_interactive`: Entrypoints used by the Docker container (`scrape_index_pipeline` is the `ENTRYPOINT`; the job definition's command args supply the subcommand and site). See "Indexing pipeline" below.

`Dockerfile`: Python 3.9 Slim image configuration.


## 🛠 Deployment to AWS

### Authenticate Docker to ECR.
```commandline
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 756132184927.dkr.ecr.us-east-2.amazonaws.com
```

### Build to make a new image.
```commandline
docker build --platform linux/amd64 -t archive-crawler .
```

### Create the history tag:

Where `[tag]` is the next iteration of the tag.

```commandline
docker tag archive-crawler:latest 756132184927.dkr.ecr.us-east-2.amazonaws.com/nara/archive-crawler:[tag]
docker push 756132184927.dkr.ecr.us-east-2.amazonaws.com/nara/archive-crawler:[tag]
```

### Update the current pointer

```commandline
docker tag archive-crawler:latest 756132184927.dkr.ecr.us-east-2.amazonaws.com/nara/archive-crawler:latest
docker push 756132184927.dkr.ecr.us-east-2.amazonaws.com/nara/archive-crawler:latest
```
