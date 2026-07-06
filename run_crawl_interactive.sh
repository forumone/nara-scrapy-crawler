#!/bin/bash

# Interactive wrapper around run_crawl.sh - prompts for each value instead
# of requiring them all as positional/flag CLI args, to reduce typos when
# constructing the command by hand. Collects and validates input, then
# delegates the actual two-phase crawl to run_crawl.sh; no crawl logic is
# duplicated here.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

prompt_url() {
    local url
    while true; do
        read -rp "Seed URL to crawl (e.g. https://example.archives.gov/): " url
        if [[ "$url" =~ ^https?:// ]]; then
            echo "$url"
            return
        fi
        echo "  Must start with http:// or https://. Try again." >&2
    done
}

prompt_site_id() {
    local site_id
    while true; do
        read -rp "Site ID (used as the output directory name, e.g. letsmove): " site_id
        if [[ "$site_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
            echo "$site_id"
            return
        fi
        echo "  Letters, digits, dots, hyphens, and underscores only - it becomes a directory name. Try again." >&2
    done
}

prompt_skip_patterns() {
    local patterns
    read -rp "Comma-separated URL patterns to skip (optional, press enter to skip): " patterns
    echo "$patterns"
}

prompt_number() {
    local label default value
    label=$1
    default=$2
    while true; do
        read -rp "$label [default: $default]: " value
        value=${value:-$default}
        if [[ "$value" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
            echo "$value"
            return
        fi
        echo "  Must be a positive number. Try again." >&2
    done
}

echo "=== Interactive crawl setup ==="
TARGET_URL=$(prompt_url)
SITE_ID=$(prompt_site_id)
SKIP_PATTERNS=$(prompt_skip_patterns)
DOWNLOAD_DELAY=$(prompt_number "Download delay in seconds" 1)
CONCURRENCY=$(prompt_number "Concurrent requests per domain" 1)

echo
echo "=== Review ==="
echo "URL:            $TARGET_URL"
echo "Site ID:        $SITE_ID"
echo "Skip patterns:  ${SKIP_PATTERNS:-<none>}"
echo "Download delay: ${DOWNLOAD_DELAY}s"
echo "Concurrency:    $CONCURRENCY"
echo

read -rp "Proceed? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

exec "$SCRIPT_DIR/run_crawl.sh" "$TARGET_URL" "$SITE_ID" "$SKIP_PATTERNS" \
    "--download-delay=$DOWNLOAD_DELAY" "--concurrency=$CONCURRENCY"
