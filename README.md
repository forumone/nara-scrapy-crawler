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

# 1. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

# 2. Install dependencies
```bash
pip install -r requirements.txt
```

---

## 🕷️ Running Locally (Development)

You can run the spider locally to test extraction logic without spinning up Docker.

### Method 1: Dry Run (No S3 Upload)
Prints JSON to the terminal. Best for debugging selectors and cleaning logic.

```bash
scrapy crawl generic_crawl \
  -a url="https://letsmove.obamawhitehouse.archives.gov/" \
  -a site_id="letsmove" \
  -a urls_to_skip="/blog/all" \
  -s FEED_URI=stdout:// \
  -s FEED_FORMAT=json \
  -s DEPTH_LIMIT=1 \
  -s CLOSESPIDER_PAGECOUNT=2
```

## 🏛️ Obama White House Spider (Three-Phase Crawl)

`obamawhitehouse.archives.gov` has no sitemap, so it uses a three-phase approach: two harvesters collect all content URLs from listing pages and site navigation, then a content spider crawls each URL.

All harvester and content CSV files are stored in the `data/` directory (git-tracked as an empty directory via `data/.gitkeep`; `.csv` files are gitignored).

### Phase A: Listing Harvest

Crawls all briefing-room listing sections and the blog, following pagination, and outputs a flat CSV of content URLs.

```bash
scrapy crawl obama_whitehouse_harvest_list -O data/www.obamawhitehouse_harvest-listing.csv
```

Expected output: ~27,000 unique URLs.

### Phase B: Nav Harvest

Starts from nav entry points, follows internal links up to depth 2, and outputs URLs reachable only through navigation (not already in the listing CSV).

```bash
scrapy crawl obama_whitehouse_harvest_nav \
  -a listing_file=data/www.obamawhitehouse_harvest-listing.csv \
  -O data/www.obamawhitehouse_harvest-nav.csv
```

The `-a listing_file` argument is optional — omit it to collect all discovered URLs without exclusions.

### Merge

Combine both harvest CSVs into a single input file for the content spider:

```bash
python merge_harvest.py \
  -o data/www.obamawhitehouse_harvest-full.csv \
  data/www.obamawhitehouse_harvest-listing.csv \
  data/www.obamawhitehouse_harvest-nav.csv
```

### Phase C: Crawl Content

Reads the merged URL file and crawls each content page.

```bash
scrapy crawl obama_whitehouse \
  -a url_file=data/www.obamawhitehouse_harvest-full.csv \
  -O data/www.obamawhitehouse.csv
```

Expected output: ~27,000 items. At the default `DOWNLOAD_DELAY=1` with ~50% redirect rate, this takes approximately 19 hours — run it on a remote server, not a local machine.

To validate against a smaller subset first, pass a reduced URL file:

```bash
scrapy crawl obama_whitehouse \
  -a url_file=data/www.obamawhitehouse_harvest-full-test.csv \
  -O data/www.obamawhitehouse-test.csv
```

---

## 🗂 CSV Naming Convention

All harvester and content output files follow a consistent naming scheme:

| File | Contents |
|---|---|
| `data/{source_site}_harvest-listing.csv` | Phase A listing harvest output |
| `data/{source_site}_harvest-nav.csv` | Phase B nav harvest output |
| `data/{source_site}_harvest-full.csv` | Merged input to content spider |
| `data/{source_site}.csv` | Final content output |

Test subsets append `-test`: `{source_site}_harvest-full-test.csv`, `{source_site}-test.csv`.

`{source_site}` matches the `SOURCE_SITE` value in the spider (e.g., `www.obamawhitehouse`).

---

## ➕ Adding a New Site

### Choosing a harvester type

- **Sitemap available?** Use a sitemap harvester (subclass `SitemapSpider`, override `sitemap_filter` to drop PDFs and apply case-insensitive deduplication). Output: `{source_site}_harvest-full.csv`.
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

### Creating a content spider

Copy `archive_crawler/spiders/obama_whitehouse.py` and update:
- `name`, `allowed_domains`, `SOURCE_SITE`, `SOURCE_TYPE`
- CSS selectors in `parse_item` to match the new site's content structure

See `archive_crawler/spiders/generic_crawl.py` for a worked example of content extraction logic.

### Validating output

```bash
# Row count
wc -l data/{source_site}.csv

# Check for empty titles or full_text (should return 0)
python -c "
import csv
with open('data/{source_site}.csv') as f:
    rows = list(csv.DictReader(f))
print('empty title:', sum(1 for r in rows if not r.get('title')))
print('empty full_text:', sum(1 for r in rows if not r.get('full_text')))
print('teaser >200:', sum(1 for r in rows if len(r.get('teaser_text','')) > 200))
"
```

---

## 📂 Project Structure

`spiders/generic_crawl.py`: The core spider. Uses CrawlSpider and LinkExtractors to walk the site. Dynamically accepts url and urls_to_skip.

`items.py`: Defines the strict JSON schema (Title, Full Text, Teaser, Date).

`run_crawl.sh`: The Entrypoint script used by the Docker container. It accepts CLI args and translates them into Scrapy commands.

Dockerfile: Python 3.9 Slim image configuration.


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