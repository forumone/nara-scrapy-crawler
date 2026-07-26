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

It's starter/example tooling, not a production-ready scraper for an arbitrary new site: phase 2's selectors are tuned to the site templates already seen in this repo, not universal. Expect to get zero or few items on a genuinely new site's first run — that means the template needs its own selectors added (or a subclass, see `crawl_spider.py`'s docstring), not that the crawl failed. `run_crawl.sh` / `run_crawl_interactive.sh` wrap this same pair for convenience; the same caveat applies to their output.

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

## 🏛️ Obama White House Spider (Unified Harvest + Content Spider)

`obamawhitehouse.archives.gov` has no sitemap. A single unified harvester,
`obama_whitehouse_harvest.py`, replaces what used to be two separate spiders
(`obama_whitehouse_harvest_nav.py` + `obama_whitehouse_harvest_list.py`) plus
a `merge_harvest.py` reconciliation step — nav-style link-following and
listing-pagination-walking now run as one spider, one pass, one output CSV.

This works because nav's own ordinary link-following (`DEPTH_LIMIT` raised
well past the mixin's usual default — see the spider's own `custom_settings`
comment for why) was already proven to reach full graph closure from the
homepage alone; the only thing it deliberately never does is follow into a
listing's own `.view` container (item rows + pager), which is what actually
protects against fanning out into that listing's full item/pagination range —
not depth limitation. `LISTING_VIEW_LINK_EXTRACTOR` (scoped to `.view`) and
`LISTING_PAGER_SELECTOR` (`'.pager-current'`), required together, are what
let the crawler safely wander into a listing page it's never seen before: it
flags the page (`is_listing=True`) instead of excluding it, and never follows
any link inside the container. Both hooks are required together — `.view`
presence alone false-positives on ordinary topic pages that merely embed a
"related videos" widget with real links but no actual pagination; requiring
a populated pager is what tells a real listing apart from one of those.

A separate, still-curated `LISTING_SEEDS` list (ported unchanged from the old
listing spider's `start_urls`) identifies which specific listings actually
get their pagination walked inline, rather than merely flagged and skipped —
this is NOT automatic for every listing the crawler flags along the way (see
the spider's own `LISTING_SEEDS` docstring for why: every
`/photos-and-video/{video,photogallery}/*` permalink embeds the exact same
sitewide catalog widget, so auto-walking every flagged listing would
re-walk that identical multi-hundred-page catalog from thousands of
different entry points).

All harvester and content CSV files are stored under `data/{source_site}/` subdirectories (the root `data/` is git-tracked via `data/.gitkeep`; `.csv` files are gitignored).

### Step 1: Unified harvest

Crawls the whole site starting from the homepage (plus the curated
`LISTING_SEEDS`), recording every page along with an `is_listing` flag and
its `depth`, and walking each curated listing's own pagination inline to
extract its item URLs directly into the same output file — no merge step
needed. `listing_file` is still a required argument (inherited from
`NavHarvesterMixin`), but there's no prior harvest to seed it with — point it
at an empty CSV (header row only):

```bash
echo "url" > data/www.obamawhitehouse/www.obamawhitehouse_empty-listing.csv

scrapy crawl obama_whitehouse_harvest \
  -a listing_file=data/www.obamawhitehouse/www.obamawhitehouse_empty-listing.csv \
  -s DOWNLOAD_DELAY=0.25 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=4 \
  -O data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv
```

Run this **untimed** (no `CLOSESPIDER_TIMEOUT`) so it actually exhausts the
site rather than stopping mid-traversal. Default scheduler (LIFO/DFS) is
fine here — BFS was only useful for validating `depth` as true shortest-path
distance during the original `DEPTH_LIMIT` tuning; the spider's own
`DEPTH_LIMIT` is now set high enough that ordering doesn't matter for
completeness either way.

### Step 2: Review new listing candidates (as needed)

Filter the output CSV for `is_listing=True` rows not already in
`LISTING_SEEDS` and spot-check them — a content page that merely embeds a
single-item view can still carry the same `.view` wrapper as a real listing,
though a populated pager block inside it is a much stronger signal than raw
`.views-row` presence alone. Confirmed new listings get added directly to
`obama_whitehouse_harvest.py`'s `LISTING_SEEDS` — this is a static, frozen
site, so the true set of listings never changes; add entries and push rather
than building a dynamic seeds-file mechanism. **Never add more than one
`/photos-and-video/video/*` or `/photos-and-video/photogallery/*` entry**
without first confirming via a fresh item-list diff that it's a genuinely
distinct, non-shared catalog (see `LISTING_SEEDS`'s own docstring).

### Step 3: Crawl content

Reads the unified harvest CSV and crawls each content page.

```bash
scrapy crawl obama_whitehouse \
  -a url_file=data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv \
  -O data/www.obamawhitehouse/www.obamawhitehouse.csv
```

At the default `DOWNLOAD_DELAY=1`, a full crawl takes a long time — run it on
a remote server, not a local machine; see "Recommended run settings" below
for throttling overrides. `parse_item` includes a `#video-info .caption`
fallback selector specifically for `/photos-and-video/video/*` gallery pages,
which otherwise extract zero body text under the standard selectors despite
often having a real, substantive caption — no boilerplate (date/duration/
download-link lines also present in that block) is stripped from it, per
this project's general preference for flagging over silent text-stripping.

---

## 🗺 Sitemap Harvester

`sitemap_harvest` is a generic, one-size-fits-all sitemap URL harvester. It fetches a sitemap (or sitemap index), recurses into all sub-sitemaps, deduplicates URLs case-insensitively, drops non-web assets (PDFs, images, etc.), and outputs a harvest CSV without fetching any content pages.

```bash
scrapy crawl sitemap_harvest \
  -a sitemap_url=https://example.archives.gov/sitemap.xml \
  -O data/example/example_harvest-full.csv
```

Expected output: one `url` column, one row per content page discovered in the sitemap.

Pass `-a dropped_file=data/example/example_harvest-dropped.csv` to also record every non-web-extension URL dropped during the harvest (PDFs, images, etc.) — a `url`/`reason` CSV, same shape as the content spiders' exclusions CSV. Without it, drops are only summarized as a count in the crawl log.

---

## 🏛️ Sitemap-Based Archive Spiders

The Clinton (CW1–6), Biden, and GWBush whitehouse spiders all follow the same two-step pattern: harvest URLs from the sitemap, then scrape content from each URL.

All spiders inherit from `ArchiveSpiderMixin` (see `archive_crawler/spiders/base.py`), which provides shared extraction logic, exclusion tracking, and HTTP error handling.

### Step 1: Harvest

Run `sitemap_harvest` once per site to collect all content URLs:

```bash
scrapy crawl sitemap_harvest \
  -a sitemap_url=https://clintonwhitehouse2.archives.gov/sitemap.xml \
  -O data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv
```

### Step 2: Scrape content

Pass the harvest CSV to the content spider:

```bash
scrapy crawl clintonwhitehouse2 \
  -a url_file=data/clintonwhitehouse2/clintonwhitehouse2_harvest-full.csv \
  -O data/clintonwhitehouse2/clintonwhitehouse2.csv
```

Replace `clintonwhitehouse2` with any of: `clintonwhitehouse1`, `clintonwhitehouse3`, `clintonwhitehouse4`, `clintonwhitehouse5`, `clintonwhitehouse6`, `bidenwhitehouse`, `georgewbush_whitehouse`.

### Pre-filtering large harvests

Some archives contain large directories of non-content URLs (print-friendly variants, image gallery wrappers, etc.). Each spider's `start_requests` filters these out at request-generation time (per `archive_crawler/exclusion_rules/<SOURCE_SITE>.yml`) and records them in the exclusions CSV. No manual pre-filtering of the harvest file is required.

### Exclusion output

Each scrape spider automatically writes a `{source_site}_exclusions.csv` alongside the output CSV when the spider closes. Each row contains the skipped URL and a typed reason:

| Reason | Description |
|---|---|
| `url_pattern:/foo/` | URL matched a known non-content path prefix |
| `frameset` | Page is a frameset with no extractable content |
| `non_text_response` | Response body isn't text (e.g. a binary file served from an extension-less URL a link-following crawl swept up) |
| `no_body` | Body selector returned empty text |
| `no_title` | No title could be extracted |
| `http_404` | HTTP 404 response |
| `http_3xx` | Redirect not followed (redirects are disabled globally) |
| `http_5xx` | Server error |
| `network_error:<type>` | Connection-level failure |

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

Large archives (CW4–6, GWBush) are best run on a remote server. Override the default throttling with Scrapy's `-s` flag, not bare environment variables — `settings.py` doesn't read `DOWNLOAD_DELAY`/`CONCURRENT_REQUESTS*` from the environment (only `FEED_URI`, `CLOSESPIDER_PAGECOUNT`, and `DEPTH_LIMIT` are), so prefixing the command with `DOWNLOAD_DELAY=0.25 ...` silently has no effect and the crawl runs at the settings.py defaults (`CONCURRENT_REQUESTS_PER_DOMAIN=1`, `DOWNLOAD_DELAY=1`):

```bash
scrapy crawl georgewbush_whitehouse \
  -s DOWNLOAD_DELAY=0.25 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=4 \
  -a url_file=data/www.georgewbush-whitehouse/georgewbush-whitehouse_harvest-full.csv \
  -O data/www.georgewbush-whitehouse/www.georgewbush-whitehouse.csv
```

Before raising throttling further, check the target domain's `robots.txt` for a `Crawl-delay` directive — `ROBOTSTXT_OBEY = False` means Scrapy won't enforce it automatically, so it's easy to run faster than the site operator has asked for without noticing.

`settings.py` also sets `MEMUSAGE_LIMIT_MB=8192` (matching `run_crawl.sh`'s default, on the assumption these run on a resource-rich remote server): if a crawl's memory footprint exceeds that (e.g. a crawler trap on a faceted-search or listing-heavy site generates unbounded unique URLs), Scrapy closes the spider gracefully and flushes the feed export, rather than the OS OOM-killing the process and losing all buffered output. Override with `-s MEMUSAGE_LIMIT_MB=N`, or via `run_crawl.sh --memory-limit=N`. `run_crawl_interactive.sh` — intended for local dev testing — prompts with half that default (4096).

---

## 🗂 CSV Naming Convention

All harvester and content output files follow a consistent naming scheme:

| File | Contents |
|---|---|
| `data/{source_site}/{source_site}_harvest-listing.csv` | Listing harvest output: content items extracted from known listing pages (split-harvester no-sitemap spiders only) |
| `data/{source_site}/{source_site}_harvest-nav.csv` | Nav harvest output: pages found by crawling site navigation, plus any `is_listing`/`depth` columns if the nav spider sets `LISTING_VIEW_LINK_EXTRACTOR` (split-harvester no-sitemap spiders only) |
| `data/{source_site}/{source_site}_harvest-full.csv` | Content-spider input: merged output for split-harvester sites (via `merge_harvest.py`), written directly by a unified harvester (e.g. `obama_whitehouse_harvest.py`) |
| `data/{source_site}/{source_site}.csv` | Final content output |
| `data/{source_site}/{source_site}_exclusions.csv` | Skipped URLs with typed reasons (written on spider close) |
| `data/{source_site}/{source_site}-errors-{timestamp}.log` | Scrapy ERROR-level log (written by `ErrorFileLogger` extension) |

Test subsets append `-test`: `{source_site}_harvest-full-test.csv`, `{source_site}-test.csv`.

`{source_site}` matches the `SOURCE_SITE` value in the spider (e.g., `www.obamawhitehouse`, `clintonwhitehouse2`).

---

## ➕ Adding a New Site

### Choosing a harvester type

- **Sitemap available?** Use `sitemap_harvest` — pass the sitemap URL and write directly to the harvest-full CSV. Output: `{source_site}_harvest-full.csv`.
- **No sitemap?** Use the split harvester pattern (nav crawl + listing harvest) described in detail in `HARVESTING.md`, worked example against Obama WH above.

To check whether a site has a sitemap, try `{base_url}/sitemap.xml` and `{base_url}/sitemap_index.xml`.

### Discovery before writing code

1. Identify listing pages (paginated archives of content — look for `.views-row` or similar list containers). Check more than one listing template if the site has more than one visual shape for listings.
2. Identify the container that wraps *both* a listing's item rows and its pager/filter controls (e.g. Drupal Views' `.view` wrapper), and a selector that only matches when a real pager is present (e.g. `.pager-current`) — a nav spider's optional `LISTING_VIEW_LINK_EXTRACTOR` + `LISTING_PAGER_SELECTOR` (required together) use these to safely flag an unknown listing page instead of needing to know about it in advance. Verify on a confirmed listing and a content page that merely embeds a single-item view or a "related content" widget — `.views-row`/`.view` presence alone isn't a reliable signal (both false-positive on embedded widgets that carry the same markup but no pagination), a populated pager is.
3. Identify nav entry points (top-level pages reachable from navigation that aren't on any listing) — often just the homepage is enough at a generous `DEPTH_LIMIT`.
4. Identify content selectors (the CSS selectors for body text and title on content pages).

### Creating a no-sitemap harvester

Two patterns exist, depending on whether the new site needs curated
pagination-walk seeds at all:

- **Unified (recommended default)** — one spider does nav-style
  link-following AND walks a curated `LISTING_SEEDS` list's pagination
  inline, no merge step. Copy `archive_crawler/spiders/obama_whitehouse_harvest.py`,
  update `name`, `allowed_domains`, `SOURCE_SITE`, `LISTING_VIEW_LINK_EXTRACTOR`/
  `LISTING_PAGER_SELECTOR`, `LISTING_SEEDS` (start empty and grow from
  reviewed `is_listing=True` output), and the listing selectors in
  `_walk_listing_pagination`. Remember to raise `DEPTH_LIMIT` well past
  whatever the longest expected pagination chain is (see that spider's own
  `custom_settings` comment for why) and to set `FEED_EXPORT_FIELDS`
  explicitly, since the spider yields both nav-flavored and bare item dicts
  in the same run.
- **Split (two spiders + `merge_harvest.py`)** — still appropriate for a
  simpler site where a separate listing-only harvester is easier to reason
  about (see `letsmove_harvest_nav.py`/`letsmove_harvest_list.py`). See
  `HARVESTING.md`'s "Step-by-step: split harvester" for the full walkthrough,
  including which ordering (nav-first vs. list-first) fits a given site and
  why.

### Creating a sitemap-based content spider

Copy an existing sitemap spider (e.g., `archive_crawler/spiders/clintonwhitehouse2.py`) and update:
- `name`, `allowed_domains`, `SOURCE_SITE`, `SOURCE_TYPE`
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

`spiders/crawl_spider.py`: Phase 2 (spider name `generic_crawl`). Reads the phase-1 harvest CSV and extracts title/body/teaser from each URL. Dynamically accepts `url_file`, `site_id`, and `source_type`.

`spiders/base.py`: `ArchiveSpiderMixin` — shared extraction, exclusion tracking, and boilerplate stripping for all archive content spiders.

`exclusion_rules.py`: Loads per-domain URL exclusion rules from `exclusion_rules/<SOURCE_SITE>.yml` (extension allow/deny list, `contains`/`regex` URL-pattern rules, nav-crawl deny patterns, generic-crawl pagination/query-param config). Every harvest-capable spider accepts `-a rules_file=<path>` and `-a rules_mode=append|replace` to overlay a per-run override on the committed file without editing it.

`exclusion_rules/`: One committed YAML file per domain (see `exclusion_rules.py` above). New sites should get one even if empty, so `-a rules_file`/`-a rules_mode` always has a base to overlay onto.

`items.py`: Defines the strict schema (Title, Full Text, Teaser, Source Site, Source Type).

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
