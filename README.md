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

`generic_crawl_harvest`/`generic_crawl` (a two-phase spider pair) run entirely locally, no Docker needed — starter/example tooling, not a production-ready scraper for an arbitrary new site. See HARVESTING.md's "Step-by-step: generic harvester" for usage and each spider's own docstring for its full `-a` argument list.

---

## 🧭 Nav Harvester Spiders (No Sitemap)

Six spiders have no sitemap to work from and instead use
`NavHarvesterMixin` (`archive_crawler/spiders/nav_harvest.py`) — one spider
per site doing nav link-following, listing-pagination-walking, and content
extraction in a single crawl:

```bash
scrapy crawl open_obama_whitehouse
```

Replace with any of: `letsmove`, `obama_whitehouse`, `obama_petitions`,
`trump_petitions`, `trumpwhitehouse`.

See [ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the listing-fingerprint mechanism these rely on — `obama_whitehouse.py`/
`letsmove.py` are its fullest worked example — and HARVESTING.md's
"Step-by-step: nav harvester" for the full walkthrough. All harvester and
content CSVs land under `data/{source_site}/` (the root `data/` is
git-tracked via `data/.gitkeep`; `.csv` files are gitignored).

---

## 🗺 Sitemap-Based Archive Spiders

The Clinton (CW1–6), Biden, and GWBush whitehouse spiders discover their
own URLs from each site's committed sitemap and scrape content in the
same run, via `SitemapUrlSpiderMixin` (`archive_crawler/spiders/base.py`):

```bash
scrapy crawl clintonwhitehouse2
```

Replace with any of: `clintonwhitehouse1`, `clintonwhitehouse3`–`6`,
`bidenwhitehouse`, `georgewbush_whitehouse`. Never pass `-O`/`-o` here —
see ARCHITECTURE.md's "Never pass `-O`/`-o` to a multi-`FEEDS`-entry
spider".

`sitemap_harvest` is the generic, one-size-fits-all sitemap URL
harvester these 8 spiders are modeled on; it's not part of running any
of them, and exists only for exploring a *new* sitemap-based site's URL
shape before writing that site's spider (see HARVESTING.md's "Sitemap
harvester" section).

---

## ⚠️ Warnings Column

`no_body`/`no_title`/`short_body` are **not** exclusions — a real page was
fetched, so it's included in the main output CSV, flagged via the
`warnings` column (comma-separated if more than one applies) instead of
being dropped:

| Warning | Meaning |
|---|---|
| `no_body` | Body selector(s) returned empty text. `full_text`/`teaser_text` are empty strings; `title` still extracted normally if present. |
| `short_body` | Body extracted fine but is under `SHORT_BODY_THRESHOLD` (default 30 chars) — override per-spider (class attribute) or per-run (`-a short_body_threshold=<N>`). |
| `no_title` | No title could be extracted. `title` falls back to `_slug_title(url)` — last URL path segment, extension stripped, `-`/`_` → spaces, no title-casing (e.g. `pp99-1.html` → `pp99 1`). This is a synthesized, not authored, title; the `warnings` column is what signals that. |

---

## 🚫 Exclusion Output

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

---

## 📊 URL Gap Analysis

`audit_url_gaps.py` compares the harvest CSV against the output CSV and groups unaccounted-for URLs by path prefix:

```bash
python audit_url_gaps.py \
  --harvest data/clintonwhitehouse2/clintonwhitehouse2_harvest.csv \
  --output  data/clintonwhitehouse2/clintonwhitehouse2.csv \
  --depth 3 \
  --source-site clintonwhitehouse2
```

Use `--depth 0` to report only the total count without path grouping.

---

## ⚙️ Recommended Run Settings

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

See HARVESTING.md for the full process — choosing a harvester type,
pre-code discovery, creating either a no-sitemap or sitemap-based spider,
and validating the output.

---

## 🔎 Push Pipeline

`scrape_index_pipeline` takes a site's content CSV through validation,
per-site warning-based row filtering, and CSV→JSONL conversion, then
pushes the result to S3. This project's responsibility ends at that
upload — a downstream Lambda watches the bucket and handles indexing
(including any reconciliation against existing index contents) on the
OpenSearch side; nothing in this repo deletes or reconciles index
contents. Three subcommands:

```bash
# Validate/filter/convert/push an existing CSV, no crawl
./scrape_index_pipeline push clintonwhitehouse1
./scrape_index_pipeline push --all

# Run the spider only - scrapy crawl <site>, nothing else
./scrape_index_pipeline crawl clintonwhitehouse1
./scrape_index_pipeline crawl --all

# Crawl the site first, then do everything push does
./scrape_index_pipeline crawl-and-push clintonwhitehouse1
./scrape_index_pipeline crawl-and-push --all
```

`<site>` is either a spider name (`bidenwhitehouse`) or a `source_site`
(`www.bidenwhitehouse`) — see `archive_crawler/pipeline/registry.py`.
`push` is the primary path: per "CSVs are frozen source of truth"
(`data/8-03/`), re-invoking a crawl is the exception, not the default
action. Run from the repo root — relative `data/` paths assume that `cwd`.

### Overrides

Run `-h` on any subcommand for the full flag list. A few behaviors worth
knowing that aren't obvious from the flag descriptions alone:

- `--csv` is `push`-only — `crawl`/`crawl-and-push` never accept a CSV
  path override, since that would mean passing `-O` to the spider, which
  silently corrupts output (see ARCHITECTURE.md's "Never pass `-O`/`-o`
  to a multi-`FEEDS`-entry spider"). Only the *converted JSONL* is
  redirectable after a crawl.
- `--logfile` diverts the *entire* crawl log away from the terminal
  (Scrapy writes to one or the other, never both); `ErrorFileLogger`'s
  own ERROR-level file keeps recording regardless. When stdout is a real
  terminal, a spinner + elapsed-seconds counter fills the gap this
  otherwise leaves blank.
- `--csv`/`--jsonl`/`--logfile`/`--filter-rules-file` cannot be combined
  with `--all` (one path can't apply to 14 sites); the throttle flags
  can.

`scrape_index_pipeline_interactive` prompts for site, mode, and any
relevant overrides instead of requiring them as CLI args, previews every
file the run will touch, and confirms before exec-ing the equivalent
`scrape_index_pipeline` command — same division of labor as the old
`run_crawl_interactive.sh` → `run_crawl.sh` pattern this replaces. Simpler
than the bare CLI by design (no `--jsonl`/`--logfile` path prompts); use
`scrape_index_pipeline` directly for finer control.

See [ARCHITECTURE.md](ARCHITECTURE.md#push-pipeline-stages-archive_crawlerpipeline)
for what each pipeline module (`registry.py`/`validate.py`/`filter_rows.py`/
`convert.py`/`push.py`) actually does.

### Credentials

`push`/`crawl-and-push` need AWS credentials and `NARA_S3_BUCKET` set to
upload. boto3's own default provider chain is used as-is — real
`AWS_ACCESS_KEY_ID`/etc. environment variables take priority if present.
Copy [.env.example](.env.example) to a gitignored `.env` to configure a
fallback credentials file/profile and the target bucket/region for a
server or workstation with no AWS environment variables of its own.

---

## 📂 Project Structure

Each file's own docstring/comments have the full detail; this is just a map.

| Path | What's there |
|---|---|
| `spiders/generic_crawl_harvest.py`, `spiders/generic_crawl.py` | The generic two-phase spider pair (see "Running Locally" above) |
| `spiders/base.py` | `ArchiveSpiderMixin`, `SitemapUrlSpiderMixin`, `PetitionsSpiderMixin` |
| `spiders/nav_harvest.py` | `NavHarvesterMixin` — see ARCHITECTURE.md |
| `spiders/exclusion_logging.py` | `ExclusionLoggingMixin` — writes `{SOURCE_SITE}_exclusions.csv` |
| `spiders/sitemap_harvest.py` | Generic sitemap onboarding harvester — see HARVESTING.md |
| `exclusion_rules.py`, `exclusion_rules/` | Per-domain URL exclusion rules — see ARCHITECTURE.md |
| `filter_rules/` | Per-`source_site` push-time warning filter — see ARCHITECTURE.md's "Push pipeline stages" |
| `items.py` | `ArchiveItem`, `HarvestItem` schemas |
| `extensions/error_log.py` | `ErrorFileLogger` |
| `audit_url_gaps.py` | Post-hoc URL gap analysis tool (see "URL Gap Analysis" above) |
| `pipeline/`, `scrape_index_pipeline`, `scrape_index_pipeline_interactive` | Push pipeline (see "Push Pipeline" above); `scrape_index_pipeline` is the Docker `ENTRYPOINT` |
| `Dockerfile` | Python 3.9 Slim image configuration |
| `crontab.example` | Example weekly re-crawl schedule for all 14 sites, 2-parallel-max |


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
