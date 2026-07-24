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

## 🏛️ Obama White House Spider (Three-Phase Crawl)

`obamawhitehouse.archives.gov` has no sitemap, so it uses a three-phase approach: two harvesters collect all content URLs from listing pages and site navigation, then a content spider crawls each URL.

All harvester and content CSV files are stored under `data/{source_site}/` subdirectories (the root `data/` is git-tracked via `data/.gitkeep`; `.csv` files are gitignored).

### Phase A: Listing Harvest

Crawls all briefing-room listing sections and the blog, following pagination, and outputs a flat CSV of content URLs.

```bash
scrapy crawl obama_whitehouse_harvest_list -O data/www.obamawhitehouse/www.obamawhitehouse_harvest-listing.csv
```

Expected output: ~27,000 unique URLs.

### Phase B: Nav Harvest

Starts from nav entry points, follows internal links up to depth 2, and outputs URLs reachable only through navigation (not already in the listing CSV).

```bash
scrapy crawl obama_whitehouse_harvest_nav \
  -a listing_file=data/www.obamawhitehouse/www.obamawhitehouse_harvest-listing.csv \
  -O data/www.obamawhitehouse/www.obamawhitehouse_harvest-nav.csv
```

### Merge

Combine both harvest CSVs into a single input file for the content spider:

```bash
python merge_harvest.py \
  -o data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv \
  data/www.obamawhitehouse/www.obamawhitehouse_harvest-listing.csv \
  data/www.obamawhitehouse/www.obamawhitehouse_harvest-nav.csv
```

### Phase C: Crawl Content

Reads the merged URL file and crawls each content page.

```bash
scrapy crawl obama_whitehouse \
  -a url_file=data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv \
  -O data/www.obamawhitehouse/www.obamawhitehouse.csv
```

Expected output: ~27,000 items. At the default `DOWNLOAD_DELAY=1` with ~50% redirect rate, this takes approximately 19 hours — run it on a remote server, not a local machine.

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
| `data/{source_site}/{source_site}_harvest-listing.csv` | Phase A listing harvest output (no-sitemap spiders) |
| `data/{source_site}/{source_site}_harvest-nav.csv` | Phase B nav harvest output (no-sitemap spiders) |
| `data/{source_site}/{source_site}_harvest-full.csv` | Merged harvest input to content spider |
| `data/{source_site}/{source_site}.csv` | Final content output |
| `data/{source_site}/{source_site}_exclusions.csv` | Skipped URLs with typed reasons (written on spider close) |
| `data/{source_site}/{source_site}-errors-{timestamp}.log` | Scrapy ERROR-level log (written by `ErrorFileLogger` extension) |

Test subsets append `-test`: `{source_site}_harvest-full-test.csv`, `{source_site}-test.csv`.

`{source_site}` matches the `SOURCE_SITE` value in the spider (e.g., `www.obamawhitehouse`, `clintonwhitehouse2`).

---

## ➕ Adding a New Site

### Choosing a harvester type

- **Sitemap available?** Use `sitemap_harvest` — pass the sitemap URL and write directly to the harvest-full CSV. Output: `{source_site}_harvest-full.csv`.
- **No sitemap?** Use the two-phase no-sitemap approach (Phase A + Phase B) as described above for Obama WH.

To check whether a site has a sitemap, try `{base_url}/sitemap.xml` and `{base_url}/sitemap_index.xml`.

### Discovery before writing code

1. Identify listing pages (paginated archives of content — look for `.views-row` or similar list containers).
2. Identify nav entry points (top-level pages reachable from navigation that aren't on any listing).
3. Identify content selectors (the CSS selectors for body text and title on content pages).

### Creating a no-sitemap harvester pair

1. Copy `archive_crawler/spiders/obama_whitehouse_harvest_list.py` and update `name`, `start_urls`, and any listing-page selectors.
2. Copy `archive_crawler/spiders/obama_whitehouse_harvest_nav.py` and update `name`, `start_urls` (nav entry points), `allowed_domains`, and the content-detection guard in `parse_nav`.
3. Run Phase A, inspect the CSV row count and a sample of URLs.
4. Run Phase B with `-a listing_file=...`, inspect the nav CSV.
5. Merge and run the content spider.

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
