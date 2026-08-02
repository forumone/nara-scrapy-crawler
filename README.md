# AWS Serverless Web Crawler for Archived Sites

This project is a containerized **Scrapy** crawler designed to run on **AWS Batch**. It serves as the data collection engine for an aggregated search system.

It is designed to crawl static/archived websites, normalize the data into a strict schema, and output JSON files to **Amazon S3**. An S3 Event Trigger then handles ingestion into **AWS OpenSearch**.

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

It's starter/example tooling, not a production-ready scraper for an arbitrary new site: phase 2's selectors are tuned to the site templates already seen in this repo, not universal. Expect to get zero or few items on a genuinely new site's first run — that means the template needs its own selectors added (or a subclass, see `generic_crawl.py`'s docstring), not that the crawl failed. `run_crawl.sh` / `run_crawl_interactive.sh` wrap this same pair for convenience; the same caveat applies to their output.

**Phase 1** (`generic_crawl_harvest`, a `CrawlSpider`) discovers URLs by following links from a seed URL:

```bash
scrapy crawl generic_crawl_harvest \
  -a url="https://letsmove.obamawhitehouse.archives.gov/" \
  -a rules_file=data/letsmove/one_off_denies.yml \
  -s DEPTH_LIMIT=1 \
  -s CLOSESPIDER_PAGECOUNT=2 \
  -O data/letsmove/letsmove_harvest-full.csv
```

`-a urls_to_skip=...` is retired — pass `-a rules_file=<path to a YAML file with a nav_deny: [...] list>` instead (optionally `-a rules_mode=replace` to override rather than append to the default). See `archive_crawler/exclusion_rules/generic_crawl_harvest.yml` for the shape, or `-a source_site=<name>` to load a specific site's own committed rules file instead of this spider's generic default.

**Phase 2** (`generic_crawl`, a plain `Spider`) reads that harvest CSV and extracts title/body/teaser from each URL — this is where selector/extraction logic actually runs, so it's the one to point at `-s FEED_URI=stdout://` when debugging cleaning logic:

```bash
scrapy crawl generic_crawl \
  -a url_file=data/letsmove/letsmove_harvest-full.csv \
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
crawl, two output files via `custom_settings['FEEDS']`. `listing_file` is
still a required argument (inherited from `NavHarvesterMixin`), but there's
no prior harvest to seed it with on a first run — point it at an empty CSV
(header row only):

```bash
echo "url" > data/www.obamawhitehouse/www.obamawhitehouse_empty-listing.csv

scrapy crawl obama_whitehouse \
  -a listing_file=data/www.obamawhitehouse/www.obamawhitehouse_empty-listing.csv \
  -s DOWNLOAD_DELAY=0.15 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=8
```

No `-O`/`-o` needed (or wanted — either would override the two-feed `FEEDS`
dict already set in `custom_settings` rather than adding to it); the harvest
and content CSVs both come from `custom_settings['FEEDS']`, at
`data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv` and
`data/www.obamawhitehouse/www.obamawhitehouse.csv` respectively.

Run this **untimed** (no `CLOSESPIDER_TIMEOUT`) so it actually exhausts the
site rather than stopping mid-traversal. Default scheduler (LIFO/DFS) is
fine here — this site's `DEPTH_LIMIT` is already tuned high enough that
ordering doesn't matter for completeness. See HARVESTING.md's nav-harvester
step 2 for when BFS actually matters vs. not.

At the default `DOWNLOAD_DELAY=1`, a full crawl takes a long time — run it on
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

Output is automatic, derived from `source_site`: the harvest CSV (one `url` column, one row per content page discovered in the sitemap) is written to `data/example/example_harvest-full.csv`. Any non-web-extension URLs dropped during the harvest (PDFs, images, etc.) are written to `data/example/example_harvest-dropped.csv` — a `url`/`reason` CSV, same shape as the content spiders' exclusions CSV — but only if at least one URL was actually dropped.

This is the one spider in the project where `-O`/`-o` do **not** control output. Pass `-a harvest_file=<path>` and/or `-a dropped_file=<path>` to override either derived default explicitly. Without `source_site`, `harvest_file` becomes required (there's no site identity to derive a path from), and dropped URLs are only summarized as a count in the crawl log unless `dropped_file` is also passed explicitly.

---

## 🏛️ Sitemap-Based Archive Spiders

The Clinton (CW1–6), Biden, and GWBush whitehouse spiders all follow the same two-step pattern: harvest URLs from the sitemap, then scrape content from each URL.

All spiders inherit from `ArchiveSpiderMixin` (see `archive_crawler/spiders/base.py`), which provides shared extraction logic, exclusion tracking, and HTTP error handling.

### Step 1: Harvest

Run `sitemap_harvest` once per site to collect all content URLs. `source_site` is what derives the output path automatically (see "Sitemap Harvester" above):

```bash
scrapy crawl sitemap_harvest \
  -a sitemap_url=https://clintonwhitehouse2.archives.gov/sitemap.xml \
  -a source_site=clintonwhitehouse2
```

This writes `data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv`.

### Step 2: Scrape content

Pass the harvest CSV to the content spider:

```bash
scrapy crawl clintonwhitehouse2 \
  -a url_file=data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv
```

Output is automatic — this writes `data/clintonwhitehouse2/clintonwhitehouse2.csv`, derived from the spider's own `SOURCE_SITE` (`custom_settings['FEEDS']`, same as every content spider in this project). Pass `-O <path>` to override.

Replace `clintonwhitehouse2` with any of: `clintonwhitehouse1`, `clintonwhitehouse3`, `clintonwhitehouse4`, `clintonwhitehouse5`, `clintonwhitehouse6`, `bidenwhitehouse`, `georgewbush_whitehouse`.

### Pre-filtering large harvests

Some archives contain large directories of non-content URLs (print-friendly variants, image gallery wrappers, etc.). Each spider's `start_requests` filters these out at request-generation time (per `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`) and records them in the exclusions CSV. No manual pre-filtering of the harvest file is required.

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
| `frameset` | Page is a frameset with no extractable content |
| `non_text_response` | Response body isn't text (e.g. a binary file served from an extension-less URL a link-following crawl swept up) |
| `http_404` | HTTP 404 response |
| `http_3xx` | Redirect not followed (redirects are disabled globally) |
| `http_5xx` | Server error |
| `network_error:<type>` | Connection-level failure |
| `search_listing_page` | `open_obama_whitehouse.py`-specific: a `/search`/`/search/type/*` pagination page - fetched and followed for dataset-link discovery, but not a content page itself |

### URL gap analysis

`audit_url_gaps.py` compares the harvest CSV against the output CSV and groups unaccounted-for URLs by path prefix:

```bash
python audit_url_gaps.py \
  --harvest data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv \
  --output  data/clintonwhitehouse2/clintonwhitehouse2.csv \
  --depth 3 \
  --source-site clintonwhitehouse2
```

Use `--depth 0` to report only the total count without path grouping.

### Recommended run settings

Large archives (CW4–6, GWBush) are best run on a remote server. Override the default throttling with Scrapy's `-s` flag, not bare environment variables — `settings.py` doesn't read `DOWNLOAD_DELAY`/`CONCURRENT_REQUESTS*` from the environment (only `FEED_URI`, `CLOSESPIDER_PAGECOUNT`, and `DEPTH_LIMIT` are), so prefixing the command with `DOWNLOAD_DELAY=0.15 ...` silently has no effect and the crawl runs at the settings.py defaults (`CONCURRENT_REQUESTS_PER_DOMAIN=1`, `DOWNLOAD_DELAY=1`):

```bash
scrapy crawl georgewbush_whitehouse \
  -s DOWNLOAD_DELAY=0.15 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=8 \
  -a url_file=data/www.georgewbush-whitehouse/georgewbush-whitehouse_harvest-full.csv
```

Before raising throttling further, check the target domain's `robots.txt` for a `Crawl-delay` directive — `ROBOTSTXT_OBEY = False` means Scrapy won't enforce it automatically, so it's easy to run faster than the site operator has asked for without noticing.

`settings.py` also sets `MEMUSAGE_LIMIT_MB=8192` (matching `run_crawl.sh`'s default, on the assumption these run on a resource-rich remote server): if a crawl's memory footprint exceeds that (e.g. a crawler trap on a faceted-search or listing-heavy site generates unbounded unique URLs), Scrapy closes the spider gracefully and flushes the feed export, rather than the OS OOM-killing the process and losing all buffered output. Override with `-s MEMUSAGE_LIMIT_MB=N`, or via `run_crawl.sh --memory-limit=N`. `run_crawl_interactive.sh` — intended for local dev testing — prompts with half that default (4096).

---

## 🗂 CSV Naming Convention

All harvester and content output files follow a consistent naming scheme. Every spider except `generic_crawl`/`generic_crawl_harvest` (one-off exploratory tools with no fixed site identity, see "Running Locally" above) writes to its own path automatically — no `-O`/`-o` needed to run a normal crawl. Each path below can still be overridden explicitly: `-O <path>` for a spider's main scrape/harvest feed (Scrapy's CLI setting replaces `custom_settings['FEEDS']` wholesale, rather than adding to it), `-a exclusions_file=<path>` for the exclusions CSV, and — for `sitemap_harvest` specifically, the one spider where `-O` doesn't apply at all — `-a harvest_file=<path>`/`-a dropped_file=<path>`.

| File | Contents |
|---|---|
| `data/{source_site}/{source_site}_harvest-listing.csv` | Listing harvest output: content items extracted from known listing pages (list-first no-sitemap pattern only, see `HARVESTING.md`) |
| `data/{source_site}/{source_site}_harvest-nav.csv` | Nav harvest output: pages found by crawling site navigation, plus any `is_listing`/`depth` columns if the nav spider sets `LISTING_VIEW_LINK_EXTRACTOR` (list-first no-sitemap pattern only) |
| `data/{source_site}/{source_site}_harvest-full.csv` | Content-spider input for sitemap-based spiders (CW1–6, Biden, GWBush) and the list-first no-sitemap pattern; one of two automatic `FEEDS` outputs from the same run for `NavHarvesterMixin` sites that also extract content (e.g. `obama_whitehouse.py`, `letsmove.py`) |
| `data/{source_site}/{source_site}.csv` | Final content output (includes a `warnings` column — see "Warnings column" above) |
| `data/{source_site}/{source_site}_exclusions.csv` | Skipped URLs with typed reasons (written on spider close) |
| `data/{source_site}/{source_site}-errors-{timestamp}.log` | Scrapy ERROR-level log (written by `ErrorFileLogger` extension) |

Test subsets append `-test`: `{source_site}_harvest-full-test.csv`, `{source_site}-test.csv`.

`{source_site}` matches the `SOURCE_SITE` value in the spider (e.g., `www.obamawhitehouse`, `clintonwhitehouse2`).

---

## ➕ Adding a New Site

### Choosing a harvester type

- **Sitemap available?** Use `sitemap_harvest` — pass the sitemap URL and `source_site`; output (`{source_site}_harvest-full.csv`) is automatic.
- **No sitemap?** Use the unified `NavHarvesterMixin` pattern described in detail in `HARVESTING.md`, worked example against Obama WH above.

To check whether a site has a sitemap, try `{base_url}/sitemap.xml` and `{base_url}/sitemap_index.xml`.

### Discovery before writing code

1. Identify listing pages (paginated archives of content — look for `.views-row` or similar list containers). Check more than one listing template if the site has more than one visual shape for listings.
2. Identify the container that wraps *both* a listing's item rows and its pager/filter controls (e.g. Drupal Views' `.view` wrapper), and a selector that only matches when a real pager is present (e.g. `.pager-current`) — a nav spider's optional `LISTING_VIEW_LINK_EXTRACTOR` + `LISTING_CONTAINER_SELECTOR` + `LISTING_PAGER_SELECTOR` (required together) use these to safely flag an unknown listing page instead of needing to know about it in advance, one container at a time if a page carries more than one. Verify on a confirmed listing and a content page that merely embeds a single-item view or a "related content" widget — `.views-row`/`.view` presence alone isn't a reliable signal (both false-positive on embedded widgets that carry the same markup but no pagination), a populated pager is.
3. Identify nav entry points (top-level pages reachable from navigation that aren't on any listing) — often just the homepage is enough at a generous `DEPTH_LIMIT`.
4. Identify content selectors (the CSS selectors for body text and title on content pages).

### Creating a no-sitemap harvester

Two patterns exist:

- **Single spider (recommended default)** — one spider does nav-style
  link-following, automatically walks every newly-discovered listing's
  pagination inline (via `NavHarvesterMixin`'s fingerprint dedup - no
  curated seed list), and extracts content on the same fetched response.
  Copy `archive_crawler/spiders/letsmove.py` (smaller, simpler starting
  point) or `archive_crawler/spiders/obama_whitehouse.py` (larger site,
  multiple listing templates), update `name`, `allowed_domains`,
  `SOURCE_SITE`, `LISTING_VIEW_LINK_EXTRACTOR`/`LISTING_CONTAINER_SELECTOR`/
  `LISTING_PAGER_SELECTOR`, implement `_listing_pagination_items`/
  `_listing_pagination_next_url` (each takes a single container Selector,
  not the full response), and write `_scrape_item` for the new site's
  content selectors (see `HARVESTING.md`'s nav-harvester walkthrough, step
  4, for the full shape including the `warnings` column). Remember to raise
  `DEPTH_LIMIT` well past whatever the longest expected pagination chain is
  (see either spider's own `custom_settings` comment for why).
- **List-first (two spiders)** — considered and rejected, not a supported
  fallback. See `HARVESTING.md`'s "List-first split harvester" section for
  why.

### Creating a sitemap-based content spider

Copy an existing sitemap spider (e.g., `archive_crawler/spiders/clintonwhitehouse2.py`) and update:
- `name`, `allowed_domains`, `SOURCE_SITE`, `SOURCE_TYPE`
- `custom_settings['FEEDS']` — one entry, keyed by the new site's own
  `data/<SOURCE_SITE>/<SOURCE_SITE>.csv` path, `item_classes: [ArchiveItem]`,
  and the same `fields` list as every other content spider (copy the exact
  shape from any existing sitemap-based spider). This is what makes the new
  spider's output automatic — no `-O` needed to run it.
- The `url_file` error message (for operator clarity)
- Create `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml` for any
  URL-pattern exclusions `start_requests` needs (`rules: [{match, pattern,
  reason}, ...]`) — see `www.georgewbush-whitehouse.yml` for an example.
  `start_requests` itself just calls `self._get_exclusion_rules()` and
  `exclusion_rules.match_exclude(url, rules)`; no per-site Python needed.
- CSS selectors in `parse_item` to match the new site's content structure

All sitemap-based spiders inherit from `ArchiveSpiderMixin`, which provides:
- `_make_request(url)` — sets up the standard callback and HTTP error errback
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
  --harvest data/{source_site}/{source_site}_harvest-full.csv \
  --output  data/{source_site}/{source_site}.csv \
  --depth 3 --source-site {source_site}
```

---

## 📂 Project Structure

`spiders/generic_crawl_harvest.py`: Phase 1 of the generic two-phase spider pair. Uses CrawlSpider and LinkExtractors to walk the site from a seed URL and write a URL-per-row CSV. Dynamically accepts `url`, `source_site`, `rules_file`, and `rules_mode`.

`spiders/generic_crawl.py`: Phase 2 (spider name `generic_crawl`). Reads the phase-1 harvest CSV and extracts title/body/teaser from each URL. Dynamically accepts `url_file`, `site_id`, and `source_type`.

`spiders/base.py`: `ArchiveSpiderMixin` — shared extraction and boilerplate stripping for all archive content spiders. Every subclass that doesn't set its own `custom_settings` gets an automatic `FEEDS` entry derived from `SOURCE_SITE`. `UrlFileSpiderMixin` (extends `ArchiveSpiderMixin`) adds `start_requests` for the sitemap-based spiders (CW1-6, Biden, GWBush) that read a `url_file` CSV - kept off `ArchiveSpiderMixin` itself so a NavHarvesterMixin-composed spider (which also extends `ArchiveSpiderMixin`, for its content-extraction helpers) falls through to `CrawlSpider`/`Spider`'s own `start_requests` without any MRO override needed. `PetitionsSpiderMixin` (the obama_petitions/trump_petitions template) and `omb_paygo_title` also live here.

`spiders/nav_harvest.py`: `NavHarvesterMixin` — shared nav link-following and listing-fingerprint pagination-walking; when a class composes both this and `ArchiveSpiderMixin` and defines `_scrape_item`, `_maybe_scrape_item` also extracts content on that same fetched response, with no second fetch.

`spiders/exclusion_logging.py`: `ExclusionLoggingMixin` — shared exclusion-rule access and logging (writes `{SOURCE_SITE}_exclusions.csv` automatically on spider close, overridable with `-a exclusions_file=<path>`) composed by both mixins above.

`spiders/sitemap_harvest.py`: Generic, one-size-fits-all sitemap URL harvester, used by all sitemap-based sites (CW1–6, Biden, GWBush). Accepts `-a sitemap_url=`, `-a source_site=`, and optional `-a rules_file=`/`-a rules_mode=`. Output paths (`{source_site}_harvest-full.csv`, `{source_site}_harvest-dropped.csv`) are automatic, derived from `source_site`, and overridable with `-a harvest_file=`/`-a dropped_file=` — the one spider in the project where `-O`/`-o` don't control output at all.

`exclusion_rules.py`: Loads per-domain URL exclusion rules from `exclusion_rules/<SOURCE_SITE>.yml` (extension allow/deny list, `contains`/`regex` URL-pattern rules, nav-crawl deny patterns, generic-crawl pagination/query-param config). Every harvest-capable spider accepts `-a rules_file=<path>` and `-a rules_mode=append|replace` to overlay a per-run override on the committed file without editing it.

`exclusion_rules/`: One committed YAML file per domain (see `exclusion_rules.py` above). New sites should get one even if empty, so `-a rules_file`/`-a rules_mode` always has a base to overlay onto.

`items.py`: `ArchiveItem` — the strict content schema (URL, Title, Full Text, Teaser, Source Site, Source Type, Warnings). `HarvestItem` — the URL/is_listing/depth schema yielded by every `NavHarvesterMixin` spider's discovery pass.

`extensions/error_log.py`: `ErrorFileLogger` — mirrors Scrapy ERROR-level log output to a per-run file alongside the output CSV.

`audit_url_gaps.py`: Post-hoc URL gap analysis tool.

`run_crawl.sh`: Entrypoint script used by the Docker container. Accepts CLI args and translates them into Scrapy commands.

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
