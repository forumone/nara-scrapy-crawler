# AWS Serverless Web Crawler for Archived Sites

This project is a containerized **Scrapy** crawler. AWS Batch deploys it. It serves as the data collection engine for an aggregated search system.

> New to this repo? See [QUICKSTART.md](QUICKSTART.md) to validate your local setup with two of the simplest crawlers before reading further.

## 🏗 Architecture

This repo crawls static, archived websites. It pushes each site's converted JSONL to an S3 bucket (see "Push Pipeline" below). A downstream Lambda, outside this repo, watches that bucket and indexes into OpenSearch. The search front end queries OpenSearch directly, through Drupal's `search_api`. Drupal does not trigger or control this repo's crawling or pushing.

What triggers a crawl remains an open question, out of scope for this repo. Options include manual invocation, `crontab.example`'s schedule, or some other interface.

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

> **Note:** `legacy-cgi` is listed in `requirements.txt`. Python 3.13+ requires it, since that version removed the `cgi` standard-library module. On earlier Python versions, it does nothing.

---

## 🕷️ Running Locally (Development)

`generic_crawl_harvest` and `generic_crawl` form a two-phase spider pair. Both run entirely locally, with no Docker needed. They are starter and example tooling, not a production-ready scraper for an arbitrary new site. See the "Step-by-step: generic harvester" section in HARVESTING.md for usage. Each spider's own docstring holds its full `-a` argument list.

---

## 🧭 Nav Harvester Spiders (No Sitemap)

Four spiders have no sitemap to work from. They use
`NavHarvesterMixin` (`archive_crawler/spiders/nav_harvest.py`) instead — one
spider per site doing nav link-following, listing-pagination-walking, and
content extraction, all in a single crawl:

```bash
./scrape_index_pipeline crawl open_obama_whitehouse
```

Replace with any of: `letsmove`, `obama_whitehouse`, `trumpwhitehouse`.

See [ARCHITECTURE.md](ARCHITECTURE.md#listing-fingerprint-dedup-navharvestermixin)
for the listing-fingerprint mechanism these spiders rely on. `obama_whitehouse.py`
and `letsmove.py` are its fullest worked example. See the "Step-by-step:
nav harvester" section in HARVESTING.md for the full walkthrough. All harvester and
content CSVs land under `data/{source_site}/`. The root `data/` directory is
git-tracked, through `data/.gitkeep`. The `.csv` files themselves are gitignored.

---

## 🗺 Sitemap-Based Archive Spiders

The Clinton (CW1 through CW6), Biden, and GWBush whitehouse spiders discover
their own URLs from each site's committed sitemap. Each one scrapes content
in the same run, through `SitemapUrlSpiderMixin` (`archive_crawler/spiders/base.py`):

```bash
./scrape_index_pipeline crawl clintonwhitehouse2
```

Replace with any of: `clintonwhitehouse1`, `clintonwhitehouse3` through `6`,
`bidenwhitehouse`, `georgewbush_whitehouse`. Never pass `-O` or `-o` here.
See the "Never pass `-O`/`-o` to a multi-`FEEDS`-entry
spider" section in ARCHITECTURE.md.

These 8 spiders each model themselves on `sitemap_harvest`, the generic,
one-size-fits-all sitemap URL harvester. It is not part of running any
of them. It exists only to explore a *new* sitemap-based site's URL
shape, before writing that site's own spider (see the "Sitemap
harvester" section in HARVESTING.md).

---

## ⚠️ Warnings Column

`no_body`, `no_title`, and `short_body` are **not** exclusions. A real
page was fetched, so the row stays in the main output CSV. The
`warnings` column flags it instead (comma-separated, if more than one
applies):

| Warning | Meaning |
|---|---|
| `no_body` | The body selectors returned empty text. `full_text`/`teaser_text` are empty strings. `title` still extracts normally, if present. |
| `short_body` | Body text was extracted, but it falls under `SHORT_BODY_THRESHOLD` (default 30 characters). Override it per-spider (class attribute) or per-run (`-a short_body_threshold=<N>`). |
| `no_title` | No title could be extracted. `title` falls back to `_slug_title(url)`: the last URL path segment. The extension gets stripped, and `-`/`_` turn to spaces. No title-casing applies (e.g. `pp99-1.html` becomes `pp99 1`). This is a synthesized title, not an authored one. The `warnings` column is what signals that. |

---

## 🚫 Exclusion & Dropped Output

Each scrape spider automatically writes up to two CSVs alongside the
output CSV, when the spider closes. No `-O`/`-a` flag is needed
(`-a exclusions_file=<path>`/`-a dropped_file=<path>` overrides either
derived default). Each row holds the skipped URL and a typed reason.
Neither file's rows ever appear in the main output CSV. The split
depends on whether a harvest row exists for the URL:

- **`{source_site}_exclusions.csv`** — a URL rejected *before* it was ever a harvest candidate, so it has no harvest row at all. For the 4 no-sitemap spiders, this means a `rules:`-matched link. Real link-following found it, then dropped it before it was ever requested. For the 8 sitemap-based spiders, this means a sitemap entry that failed the extension allowlist, or matched a `rules:` entry. Either way, the spider dropped it before writing a harvest row for it. Read this file for a per-rule audit of what got excluded, and why.
- **`{source_site}_dropped.csv`** — a URL that already has a harvest row, then got rejected. This happens post-fetch (a bad response) or post-harvest-row (fetched fine, judged non-content).

Two invariants hold for every one of the 12 in-scope sites. **`scraped + dropped = harvested`** always holds. For the 8 sitemap-based spiders specifically, **`harvested + excluded = sitemap total`** also holds. The 4 no-sitemap spiders have no fixed "total" to reconcile `excluded` against. A nav crawl's link-discovery has no fixed URL list to bound it, unlike a sitemap.

| Reason | File | Description |
|---|---|---|
| `url_pattern:/foo/` | Exclusions | The URL matched a known non-content path prefix. |
| `extension:<ext>` | Exclusions | Sitemap-based spiders only (CW1–6, Biden, GWBush). The sitemap entry failed the site's extension allowlist (e.g. a PDF or image). `NavHarvesterMixin`-based spiders (all 4 no-sitemap spiders) filter the same way during link-following. They do not log it — see "Watch out for" below. |
| `frameset` | Dropped | The page is a frameset with no extractable content. |
| `non_text_response` | Dropped | The response body is not text. Example: a binary file, served from an extension-less URL a link-following crawl swept up. |
| `http_404` | Dropped | The page returned an HTTP 404. |
| `http_3xx` | Dropped | A redirect went unfollowed (redirects are disabled globally). |
| `http_5xx` | Dropped | The server returned an error. |
| `network_error:<type>` | Dropped | The connection failed at the network level. |
| `search_listing_page` | Dropped | `open_obama_whitehouse.py`-specific: a `/search`/`/search/type/*` pagination page, followed only for dataset-link discovery. |
| `pagination_listing_page` | Dropped | `PetitionsSpiderMixin`-specific: a root or `/responses` pagination page (`?page=N`), followed only for petition-link discovery. |
| `listing_page` | Dropped | `NavHarvesterMixin`-specific (all 4 no-sitemap spiders): the page has a detected listing container (see ARCHITECTURE.md). Its own content goes unscraped. |

**Watch out for**: `NavHarvesterMixin`-based spiders (the 4 no-sitemap
sites) never log a link that `_filter_web_urls` drops for failing the
extension allowlist. That link is silently excluded from following,
with no `extension:*` row anywhere, unlike the 8 sitemap-based spiders'
own extension-allowlist rejections during sitemap parsing.
`_walk_listing_pagination`'s own pagination-continuation pages (page 2,
3, and on) never get a harvest row either way. A `non_text_response`
logged there does not count toward `scraped + dropped = harvested` — it
is diagnostic only. The standalone `sitemap_harvest.py` exploration
tool keeps its own unrelated `{source_site}_harvest-dropped.csv` (for
sitemap-listed URLs that fail its own extension check), separate from
everything above.

---

## 📊 URL Gap Analysis

`audit_url_gaps.py` compares the harvest CSV against the output CSV, and groups unaccounted-for URLs by path prefix:

```bash
python audit_url_gaps.py \
  --harvest data/clintonwhitehouse2/clintonwhitehouse2_harvest.csv \
  --output  data/clintonwhitehouse2/clintonwhitehouse2.csv \
  --depth 3 \
  --source-site clintonwhitehouse2
```

Use `--depth 0` to report only the total count, with no path grouping.

---

## ⚙️ Recommended Run Settings

Run large archives (CW4–6, GWBush) on a remote server. Always launch
through `scrape_index_pipeline`, never a bare `scrapy crawl` — see
"Always use the wrapper" below. Override the default throttling with
`--download-delay`/`--concurrent-requests-per-domain`, not a bare
environment variable. `settings.py` does not read
`DOWNLOAD_DELAY`/`CONCURRENT_REQUESTS*` from the environment (only
`FEED_URI`, `CLOSESPIDER_PAGECOUNT`, and `DEPTH_LIMIT` do). Prefixing
the command with `DOWNLOAD_DELAY=0.15 ...` silently does nothing, and
the crawl runs at the `settings.py` defaults
(`CONCURRENT_REQUESTS_PER_DOMAIN=4`, `DOWNLOAD_DELAY=0.25`) instead.

The right override on the remote server depends on how many crawls are
running there *concurrently*. The shared constraint is combined
outbound load, not any single crawl's own politeness:

| concurrent crawls | `DOWNLOAD_DELAY` | `CONCURRENT_REQUESTS_PER_DOMAIN` |
|---|---|---|
| 1 | 0.12 | 10 |
| 2 | 0.15 | 8 |
| 3 | 0.2 | 6 |
| 4–5 | 0.25 | 4 (matches the local default — no override needed) |
| 6–7 | 0.5 | 2 |
| 8+ | 1 | 1 |

```bash
./scrape_index_pipeline crawl georgewbush_whitehouse \
  --download-delay 0.12 \
  --concurrent-requests-per-domain 10
```

To launch on the remote server itself, SSH in. Background the crawl
with `nohup`/`disown`, so it survives a disconnect. Point `--logfile`
at a path under that site's `data/{site}/` directory, to monitor
progress:

```bash
ssh user@example-remote-host \
  "cd /home/scrapy/nara-scrapy-crawler && \
   nohup ./scrape_index_pipeline crawl obama_whitehouse \
     --download-delay 0.12 \
     --concurrent-requests-per-domain 10 \
     --logfile data/www.obamawhitehouse/obama_whitehouse-20261231.log \
     > /dev/null 2>&1 & disown"
```

Launch only one crawl per SSH invocation. Chaining several backgrounded
launches together in a single call is unreliable, and can silently
drop some of them. The SSH command itself may hang past a client-side
timeout, until the entire remote process tree exits, including the
disowned job. That is expected, not a stuck connection. Its eventual
return is a reliable signal the crawl actually finished.

Before raising throttling further, check the target domain's
`robots.txt` for a `Crawl-delay` directive. `ROBOTSTXT_OBEY = False`
means Scrapy will not enforce it automatically, so it is easy to run
faster than the site operator has asked for, without noticing.

`settings.py` also sets `MEMUSAGE_LIMIT_MB=8192`, on the assumption
these crawls run on a resource-rich remote server. If a crawl's memory
footprint exceeds that limit (for example, a crawler trap on a
faceted-search or listing-heavy site generates unbounded unique URLs),
Scrapy closes the spider gracefully and flushes the feed export. The OS
never gets the chance to OOM-kill the process and lose all buffered
output. Override it per-run with `--memusage-limit N` on `crawl`/
`crawl-and-push` (for example, a lower value for local dev testing).

---

## 🛡 Always Use the Wrapper

For every one of the 12 in-scope content spiders, launch through
`./scrape_index_pipeline crawl`/`crawl-and-push`, never a bare `scrapy
crawl <site>` call. This is not only a style preference.
`scrape_index_pipeline`'s own `_crawl` step checks the spider process's
exit code before continuing. A `crawl-and-push` run whose crawl exits
nonzero never reaches `push` at all. A bare `scrapy crawl`, run by
hand or scripted outside the wrapper, has no such gate. Nothing stops
its output from being pushed later, by a separate `push` call, with no
record of whether that crawl actually finished.

`generic_crawl`, `generic_crawl_harvest`, and `sitemap_harvest` are the
exception. All three are one-off exploratory tools for a site not yet
onboarded (see HARVESTING.md), outside `scrape_index_pipeline`'s own
site registry (`archive_crawler/pipeline/registry.py`) by design. They
have no wrapper equivalent, and running them directly is correct.

## 🗂 CSV Naming Convention

All harvester and content output files follow one consistent naming
scheme. Every spider writes to its own path automatically, except
`generic_crawl`/`generic_crawl_harvest`. Those two are one-off
exploratory tools with no fixed site identity (see "Running Locally"
above), and the only two spiders that still require `-O`/`-o` for any
output at all. Do not pass `-O <path>` to any of the 12 in-scope
content spiders, to redirect their output. Every one of them has a
two-entry `custom_settings['FEEDS']` (harvest and content). Scrapy's
CLI setting replaces that whole dict, rather than adding to it, which
silently drops the harvest CSV and corrupts the content CSV's own shape
(see ARCHITECTURE.md). Use `-a exclusions_file=<path>`/`-a dropped_file=<path>`
for the exclusions/dropped CSVs. For `sitemap_harvest` specifically,
where `-O` does not apply at all, use `-a harvest_file=<path>`/`-a dropped_file=<path>`
(its own, unrelated `dropped_file`).

| File | Contents |
|---|---|
| `data/{source_site}/{source_site}_harvest.csv` | One of two automatic `FEEDS` outputs from the same run: the surviving URL list. This applies to both sitemap-based spiders (CW1–6, Biden, GWBush) and `NavHarvesterMixin` sites that also extract content (e.g. `obama_whitehouse.py`, `letsmove.py`). |
| `data/{source_site}/{source_site}.csv` | The final content output (includes a `warnings` column — see "Warnings column" above). |
| `data/{source_site}/{source_site}_exclusions.csv` | Skipped URLs with typed reasons (written when the spider closes). |
| `data/{source_site}/{source_site}-errors-{timestamp}.log` | The Scrapy ERROR-level log (written by the `ErrorFileLogger` extension). |

Test subsets append `-test`: `{source_site}_harvest-test.csv`, `{source_site}-test.csv`.

`{source_site}` matches the `SOURCE_SITE` value in the spider (for example, `www.obamawhitehouse`, `clintonwhitehouse2`).

---

## ➕ Adding a New Site

See HARVESTING.md for the full process: choosing a harvester type,
pre-code discovery, creating either a no-sitemap or sitemap-based
spider, and validating the output.

---

## 🔎 Push Pipeline

`scrape_index_pipeline` takes a site's content CSV through validation,
per-site warning-based row filtering, and CSV-to-JSONL conversion, then
pushes the result to S3. This project's responsibility ends at that
upload. A downstream Lambda watches the bucket, and handles indexing
on the OpenSearch side (including any reconciliation against existing
index contents). Nothing in this repo deletes or reconciles index
contents. Three subcommands:

```bash
# Validate/filter/convert/push an existing CSV, no crawl
./scrape_index_pipeline push clintonwhitehouse1

# Run the spider only - scrapy crawl <site>, nothing else
./scrape_index_pipeline crawl clintonwhitehouse1

# Crawl the site first, then do everything push does
./scrape_index_pipeline crawl-and-push clintonwhitehouse1
```

`<site>` is either a spider name (`bidenwhitehouse`) or a `source_site`
(`www.bidenwhitehouse`) — see `archive_crawler/pipeline/registry.py`.
`push` is the primary path. Per "CSVs are frozen source of truth"
(`data/8-03/`), re-invoking a crawl is the exception, not the default
action. Run this from the repo root. The relative `data/` paths assume
that working directory.

Every command takes exactly one site — there is no `--all`. To run
against every site, call the command once per site, the way
`crontab.example` does. Each call gets its own exit code, and one site
aborting never blocks the sites after it.

### Overrides

Run `-h` on any subcommand for the full flag list. A few behaviors are
worth knowing, that are not obvious from the flag descriptions alone:

- `--csv` is `push`-only. `crawl`/`crawl-and-push` never accept a CSV path override. Passing `-O` to the spider would silently corrupt output. See the "Never pass `-O`/`-o` to a multi-`FEEDS`-entry spider" section in ARCHITECTURE.md. Only the *converted JSONL* is redirectable after a crawl.
- `--logfile` diverts the *entire* crawl log away from the terminal (Scrapy writes to one or the other, never both). `ErrorFileLogger`'s own ERROR-level file keeps recording regardless. When stdout is a real terminal, a spinner and an elapsed-seconds counter fill the gap this otherwise leaves blank.
- `push`/`crawl-and-push` run four checks before uploading anything, none skippable by `--bypass` except the last. A 0-row CSV always aborts, with no override — a network or server outage can leave a crawl with nothing to push, and the downstream Lambda's mark-and-sweep should never read that as "the site now has zero pages." A missing `*_dropped.csv` also always aborts, with no override — `ExclusionLoggingMixin` writes that file on every clean spider close, even with zero rows, so its absence means the crawl crashed before finishing, not that it ran clean. A hand-built `--csv` needs a placeholder dropped-log (header row, zero data rows) alongside it to pass this check. A lost sitemap or listing-pagination request also always aborts, with no override — that single lost request costs every page past it, not just one page, so it is never averaged against a threshold. A plain HTTP 404 on either kind of request is the one exception, treated as an ordinary, harmless 404, since it means the resource does not exist rather than that the crawl lost access to it. Only the fourth check, ordinary `http_5xx`/`network_error` rows on individual content pages, respects `--error-threshold N` and `--bypass`: it aborts when the site's `*_dropped.csv` has at least N such rows, since a partial outage can still leave real, nonzero rows behind while sweeping away every URL that failed to fetch this run. Each site's spider class sets its own default threshold through `ERROR_THRESHOLD` (see ARCHITECTURE.md), normally 1. Passing `--error-threshold` on the CLI always overrides that default. `--bypass` skips only this fourth check.

`scrape_index_pipeline_interactive` prompts for site, mode, and any
relevant overrides, instead of requiring them as CLI arguments. It
previews every file the run will touch, and confirms before running the
equivalent `scrape_index_pipeline` command — the same division of labor
as the old `run_crawl_interactive.sh` and `run_crawl.sh` pattern this
replaces. It is simpler than the bare CLI by design (no `--jsonl`/`--logfile`
path prompts). Use `scrape_index_pipeline` directly for finer control.

See [ARCHITECTURE.md](ARCHITECTURE.md#push-pipeline-stages-archive_crawlerpipeline)
for what each pipeline module (`registry.py`/`validate.py`/`filter_rows.py`/
`convert.py`/`push.py`) actually does.

### Credentials

`push`/`crawl-and-push` need AWS credentials, and `NARA_S3_BUCKET` set,
to upload. This project uses boto3's own default provider chain as-is.
Real `AWS_ACCESS_KEY_ID` and similar environment variables take
priority, when present. Copy [.env.example](.env.example) to a
gitignored `.env`, to configure a fallback credentials file or profile,
and the target bucket and region, for a server or workstation with no
AWS environment variables of its own.

---

## 📂 Project Structure

Each file's own docstring or comments carry the full detail. This is just a map.

| Path | What is there |
|---|---|
| `spiders/generic_crawl_harvest.py`, `spiders/generic_crawl.py` | The generic two-phase spider pair (see "Running Locally" above) |
| `spiders/base.py` | `ArchiveSpiderMixin`, `SitemapUrlSpiderMixin`, `PetitionsSpiderMixin` |
| `spiders/nav_harvest.py` | `NavHarvesterMixin` — see ARCHITECTURE.md |
| `spiders/exclusion_logging.py` | `ExclusionLoggingMixin` — writes `{SOURCE_SITE}_exclusions.csv` |
| `spiders/sitemap_harvest.py` | Generic sitemap onboarding harvester — see HARVESTING.md |
| `exclusion_rules.py`, `exclusion_rules/` | Per-domain URL exclusion rules — see ARCHITECTURE.md |
| `filter_rules/` | Per-`source_site` push-time warning filter — see the "Push pipeline stages" section in ARCHITECTURE.md |
| `items.py` | `ArchiveItem`, `HarvestItem` schemas |
| `extensions/error_log.py` | `ErrorFileLogger` |
| `audit_url_gaps.py` | Post-hoc URL gap analysis tool (see "URL Gap Analysis" above) |
| `pipeline/`, `scrape_index_pipeline`, `scrape_index_pipeline_interactive` | Push pipeline (see "Push Pipeline" above). `scrape_index_pipeline` is the Docker `ENTRYPOINT` |
| `Dockerfile` | Python 3.9 Slim image configuration |
| `crontab.example` | Example weekly re-crawl schedule for all 12 sites, 2-parallel-max |


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
