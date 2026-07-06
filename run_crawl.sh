#!/bin/bash

# Usage: ./run_crawl.sh <URL> <SITE_ID> <URLS_TO_SKIP>
#
# Runs the two-phase generic_crawl workflow: harvest URLs from a seed URL
# (generic_crawl_harvest), then scrape title/body/teaser from each one
# (generic_crawl).

set -euo pipefail

TARGET_URL=${1:-}
SITE_ID=${2:-}
SKIP_PATTERNS=${3:-}

if [ -z "$TARGET_URL" ] || [ -z "$SITE_ID" ]; then
    echo "Error: URL and SITE_ID are required"
    echo "Usage: ./run_crawl.sh <URL> <SITE_ID> <URLS_TO_SKIP>"
    exit 1
fi

HARVEST_FILE="data/${SITE_ID}/${SITE_ID}_harvest-full.csv"
OUTPUT_FILE="data/${SITE_ID}/${SITE_ID}.csv"

echo "Phase 1: Harvesting URLs from $TARGET_URL"
echo "Restricted to domain of that URL."

HARVEST_ARGS=(crawl generic_crawl_harvest -a "url=$TARGET_URL" -O "$HARVEST_FILE")
if [ -n "$SKIP_PATTERNS" ]; then
    echo "Skipping patterns: $SKIP_PATTERNS"
    HARVEST_ARGS+=(-a "urls_to_skip=$SKIP_PATTERNS")
fi
scrapy "${HARVEST_ARGS[@]}"

echo "Phase 2: Scraping content for each harvested URL"
scrapy crawl generic_crawl -a "url_file=$HARVEST_FILE" -a "site_id=$SITE_ID" -O "$OUTPUT_FILE"
