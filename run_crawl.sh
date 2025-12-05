#!/bin/bash

# Usage: ./run_crawl.sh <URL> <SITE_ID> <URLS_TO_SKIP>

TARGET_URL=$1
SITE_ID=$2
SKIP_PATTERNS=$3

if [ -z "$TARGET_URL" ]; then
    echo "Error: No URL supplied"
    exit 1
fi

echo "Starting Deep Crawl for: $TARGET_URL"
echo "Restricted to domain of that URL."

# Construct the command
CMD="scrapy crawl generic_crawl -a url=\"$TARGET_URL\" -a site_id=\"$SITE_ID\""

if [ ! -z "$SKIP_PATTERNS" ]; then
    echo "Skipping patterns: $SKIP_PATTERNS"
    CMD="$CMD -a urls_to_skip=\"$SKIP_PATTERNS\""
fi

eval $CMD