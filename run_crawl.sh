#!/bin/bash

# Usage: ./run_crawl.sh <URL> <SITE_ID> [URLS_TO_SKIP] [--download-delay=N] [--concurrency=N] [--memory-limit=N]
#
# Runs the two-phase generic_crawl workflow: harvest URLs from a seed URL
# (generic_crawl_harvest), then scrape title/body/teaser from each one
# (generic_crawl). --download-delay and --concurrency map to Scrapy's
# DOWNLOAD_DELAY and CONCURRENT_REQUESTS_PER_DOMAIN settings (default 1
# each, matching settings.py) and apply to both phases. --memory-limit maps
# to MEMUSAGE_LIMIT_MB (default 8192, matching settings.py, on the assumption
# this script runs on a resource-rich remote server) — if a crawl exceeds
# this, Scrapy closes the spider gracefully (flushing the feed export)
# instead of the OS OOM-killing it outright. run_crawl_interactive.sh halves
# this default for local dev testing.

set -euo pipefail

DOWNLOAD_DELAY=1
CONCURRENCY=1
MEMORY_LIMIT=8192
POSITIONAL=()

for arg in "$@"; do
    case "$arg" in
        --download-delay=*)
            DOWNLOAD_DELAY="${arg#*=}"
            ;;
        --concurrency=*)
            CONCURRENCY="${arg#*=}"
            ;;
        --memory-limit=*)
            MEMORY_LIMIT="${arg#*=}"
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

HARVEST_FILE="data/${SITE_ID}/${SITE_ID}_harvest.csv"
OUTPUT_FILE="data/${SITE_ID}/${SITE_ID}.csv"

echo "Phase 1: Harvesting URLs from $TARGET_URL"
echo "Restricted to domain of that URL. delay=${DOWNLOAD_DELAY}s concurrency=${CONCURRENCY} memory-limit=${MEMORY_LIMIT}MB"

HARVEST_ARGS=(crawl generic_crawl_harvest -a "url=$TARGET_URL" \
    -s "DOWNLOAD_DELAY=$DOWNLOAD_DELAY" -s "CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENCY" \
    -s "MEMUSAGE_LIMIT_MB=$MEMORY_LIMIT" \
    -O "$HARVEST_FILE")
if [ -n "$SKIP_PATTERNS" ]; then
    echo "Skipping patterns: $SKIP_PATTERNS"
    # generic_crawl_harvest no longer takes a urls_to_skip arg directly
    # (retired 2026-07-24 in favor of exclusion_rules YAML) - translate
    # the same comma-separated regex fragments into a one-off nav_deny
    # rules_file instead, appended onto generic_crawl_harvest.yml's own
    # default rules.
    SKIP_RULES_FILE=$(mktemp --suffix=.yml)
    trap 'rm -f "$SKIP_RULES_FILE"' EXIT
    {
        echo "nav_deny:"
        IFS=',' read -ra SKIP_PATTERN_LIST <<< "$SKIP_PATTERNS"
        for pattern in "${SKIP_PATTERN_LIST[@]}"; do
            pattern="$(echo "$pattern" | xargs)"
            printf "  - '%s'\n" "$pattern"
        done
    } > "$SKIP_RULES_FILE"
    HARVEST_ARGS+=(-a "rules_file=$SKIP_RULES_FILE" -a "rules_mode=append")
fi
scrapy "${HARVEST_ARGS[@]}"

echo "Phase 2: Scraping content for each harvested URL"
scrapy crawl generic_crawl \
    -a "url_file=$HARVEST_FILE" -a "site_id=$SITE_ID" \
    -s "DOWNLOAD_DELAY=$DOWNLOAD_DELAY" -s "CONCURRENT_REQUESTS_PER_DOMAIN=$CONCURRENCY" \
    -s "MEMUSAGE_LIMIT_MB=$MEMORY_LIMIT" \
    -O "$OUTPUT_FILE"

ITEM_COUNT=0
if [ -s "$OUTPUT_FILE" ]; then
    ITEM_COUNT=$(($(wc -l < "$OUTPUT_FILE") - 1))
fi
echo
echo "Phase 2 complete: ${ITEM_COUNT} item(s) written to $OUTPUT_FILE"
if [ "$ITEM_COUNT" -le 0 ]; then
    echo "generic_crawl's selectors are tuned to known site templates, not universal - a zero count"
    echo "usually means this site's markup doesn't match them yet, not that the crawl failed. See"
    echo "HARVESTING.md and generic_crawl.py's docstring for how to extend or subclass it."
fi
