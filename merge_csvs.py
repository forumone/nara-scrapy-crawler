#!/usr/bin/env python3
"""Merge two or more CSVs into a single file with one header row.

Not currently used by any spider or documented workflow in this repo - kept
as a general-purpose utility script for a future one-off need.

Inputs do not need identical columns. The merged file's header is the union
of all input columns, in first-seen order; rows from a file missing a given
column get '' for it.

Rows are deduplicated by 'url': for a URL appearing in more than one input,
only the row from the first file listing it is kept.

Usage:
    python merge_csvs.py \\
        -o merged.csv \\
        input1.csv \\
        input2.csv
"""

import argparse
import csv


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-o', '--output', required=True, metavar='FILE',
                        help='output CSV path')
    parser.add_argument('inputs', nargs='+', metavar='FILE',
                        help='input CSV files to merge (in order)')
    args = parser.parse_args()

    fieldnames = []
    seen = set()
    for path in args.inputs:
        with open(path, newline='', encoding='utf-8-sig') as in_f:
            for name in csv.DictReader(in_f).fieldnames:
                if name not in seen:
                    seen.add(name)
                    fieldnames.append(name)

    seen_urls = set()
    merged_rows = []
    total = 0
    duplicates = 0
    for path in args.inputs:
        with open(path, newline='', encoding='utf-8-sig') as in_f:
            rows = list(csv.DictReader(in_f))
            total += len(rows)
            kept = 0
            for row in rows:
                if row['url'] in seen_urls:
                    duplicates += 1
                    continue
                seen_urls.add(row['url'])
                merged_rows.append(row)
                kept += 1
            print(f'  {len(rows):>6} rows ({kept} new)  {path}')

    with open(args.output, 'w', newline='', encoding='utf-8-sig') as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames, restval='')
        writer.writeheader()
        writer.writerows(merged_rows)

    print(f'  {total:>6} rows read, {duplicates} duplicate url(s) dropped, '
          f'{len(merged_rows)} rows written -> {args.output}')
    print(f'  columns: {fieldnames}')


if __name__ == '__main__':
    main()
