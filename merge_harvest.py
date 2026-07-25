#!/usr/bin/env python3
"""Merge two or more harvest CSVs into a single file with one header row.

Inputs do not need identical columns - e.g. a nav harvester's url/is_listing/
depth output can be merged with a listing harvester's url-only output. The
merged file's header is the union of all input columns, in first-seen order;
rows from a file missing a given column get '' for it.

Usage:
    python merge_harvest.py \\
        -o data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv \\
        data/www.obamawhitehouse/www.obamawhitehouse_harvest-listing.csv \\
        data/www.obamawhitehouse/www.obamawhitehouse_harvest-nav.csv
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

    total = 0
    with open(args.output, 'w', newline='', encoding='utf-8-sig') as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames, restval='')
        writer.writeheader()
        for path in args.inputs:
            with open(path, newline='', encoding='utf-8-sig') as in_f:
                rows = list(csv.DictReader(in_f))
                writer.writerows(rows)
                total += len(rows)
                print(f'  {len(rows):>6} rows  {path}')

    print(f'  {total:>6} rows total -> {args.output}')
    print(f'  columns: {fieldnames}')


if __name__ == '__main__':
    main()
