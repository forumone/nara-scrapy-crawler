#!/bin/bash

# Usage: ./run_crawl.sh <URL> <SITE_ID> [URLS_TO_SKIP] [--download-delay=N] [--concurrency=N]
#
# Runs the two-phase generic_crawl workflow: harvest URLs from a seed URL
# (generic_crawl_harvest), then scrape title/body/teaser from each one
# (generic_crawl). --download-delay and --concurrency map to Scrapy's
# DOWNLOAD_DELAY and CONCURRENT_REQUESTS_PER_DOMAIN settings (default 1
# each, matching settings.py) and apply to both phases.

set -euo pipefail

DOWNLOAD_DELAY=1
CONCURRENCY=1
POSITIONAL=()

for arg in "$@"; do
    case "$arg" in
        --download-delay=*)
            DOWNLOAD_DELAY="${arg#*=}"
            ;;
        --concurrency=*)
            CONCURRENCY="${arg#*=}"
            ;;
        *)
            POSITIONAL+=("$arg")
            ;;
    esac
done

TARGET_URL=${POSITIONAL[0]:-}
SITE_ID=${POSITIONAL[1]:-}
SKIP_PATTERNS=${POSITIONAL[2]:-}

if [ -z "$TARGET_URL" ] || [ -z "$SITE_ID" ]; then
    echo "Error: URL and SITE_ID are required"
    echo "Usage: ./run_crawl.sh <URL> <SITE_ID> [URLS_TO_SKIP] [--download-delay=N] [--concurrency=N]"
    exit 1
fi

HARVEST_FILE="data/${SITE_ID}/${SITE_ID}_harvest-full.csv"
OUTPUT_FILE="data/${SITE_ID}/${SITE_ID}.csv"

echo "Phase 1: Harvesting URLs from $TARGET_URL"
echo "Restricted to domain of that URL. delay=${DOWNLOAD_DELAY}s concurrency=${CONCURRENCY}"

HARVEST_ARGS=(crawl generic_crawl_harvest -a "url=$TARGET_URL" \
    -s "DOWNLOAD_DELAY=$DOWNLOAD_DELAY" -s "CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENCY" \
    -O "$HARVEST_FILE")
if [ -n "$SKIP_PATTERNS" ]; then
    echo "Skipping patterns: $SKIP_PATTERNS"
    HARVEST_ARGS+=(-a "urls_to_skip=$SKIP_PATTERNS")
fi
scrapy "${HARVEST_ARGS[@]}"

echo "Phase 2: Scraping content for each harvested URL"
scrapy crawl generic_crawl \
    -a "url_file=$HARVEST_FILE" -a "site_id=$SITE_ID" \
    -s "DOWNLOAD_DELAY=$DOWNLOAD_DELAY" -s "CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENCY" \
    -O "$OUTPUT_FILE"
