#!/usr/bin/env python3
"""Post-hoc URL gap analysis: harvest CSV vs. output CSV.

For each URL in the harvest that is absent from the output, reports the total
count and groups by path prefix at a configurable depth.

Usage:
    python audit_url_gaps.py \
        --harvest data/www.georgewbush-whitehouse/georgewbush-whitehouse_harvest-full.csv \
        --output  data/www.georgewbush-whitehouse/www.georgewbush-whitehouse.csv \
        [--depth 3] [--top 30] [--source-site "GW Bush"]

Use --depth 0 to skip path grouping and report only the total count.
"""
import argparse
import csv
import sys
from collections import Counter
from urllib.parse import urlparse


def path_prefix(url, depth):
    parts = urlparse(url).path.strip('/').split('/')
    prefix = '/' + '/'.join(parts[:depth])
    return prefix + ('/' if len(parts) > depth else '')


def load_urls(path):
    csv.field_size_limit(sys.maxsize)
    with open(path, newline='', encoding='utf-8-sig') as f:
        return [row['url'] for row in csv.DictReader(f)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--harvest', required=True, help='Harvest CSV path (url column required)')
    parser.add_argument('--output', required=True, help='Scraped output CSV path (url column required)')
    parser.add_argument('--depth', type=int, default=3, help='Path segments to group by (0 = no grouping)')
    parser.add_argument('--top', type=int, default=30, help='Max prefix rows to display')
    parser.add_argument('--source-site', default='', help='Label for the report header')
    args = parser.parse_args()

    harvest_urls = load_urls(args.harvest)
    output_urls = set(load_urls(args.output))

    harvest_counts = Counter(harvest_urls)
    duplicates = sum(c - 1 for c in harvest_counts.values() if c > 1)
    unique_harvest = list(harvest_counts.keys())

    missing = [u for u in unique_harvest if u not in output_urls]

    label = args.source_site or args.harvest
    width = 60
    print(f"\n{'=' * width}")
    print(f"  URL gap report: {label}")
    print(f"{'=' * width}")
    print(f"  Harvest rows  : {len(harvest_urls):>7,}")
    if duplicates:
        print(f"  Duplicates    : {duplicates:>7,}  (dropped by Scrapy dupe filter)")
    print(f"  Unique harvest: {len(unique_harvest):>7,}")
    print(f"  Output total  : {len(output_urls):>7,}")
    missing_pct = 100 * len(missing) / len(unique_harvest) if unique_harvest else 0
    print(f"  Missing       : {len(missing):>7,}  ({missing_pct:.1f}% of unique harvest)")

    if not missing:
        print("\n  No missing URLs.\n")
        return

    if args.depth <= 0:
        print(f"\n  (--depth 0: no path grouping)\n")
        return

    counts = Counter(path_prefix(u, args.depth) for u in missing)
    shown = counts.most_common(args.top)
    remainder = len(counts) - len(shown)

    print(f"\n  Missing by path prefix (depth={args.depth}), top {args.top}:")
    print(f"  {'Count':>7}  {'%miss':>6}  Prefix")
    print(f"  {'-------':>7}  {'------':>6}  {'-' * 50}")
    for prefix, count in shown:
        pct = 100 * count / len(missing)
        print(f"  {count:>7,}  {pct:>5.1f}%  {prefix}")
    if remainder:
        rest_count = sum(c for _, c in counts.most_common()[args.top:])
        print(f"  {rest_count:>7,}         ({remainder} more prefixes)")
    print()


if __name__ == '__main__':
    main()
