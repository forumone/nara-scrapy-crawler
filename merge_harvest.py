#!/usr/bin/env python3
"""Merge two or more harvest CSVs into a single file with one header row.

Usage:
    python merge_harvest.py \\
        -o data/www.obamawhitehouse/www.obamawhitehouse_harvest-full.csv \\
        data/www.obamawhitehouse/www.obamawhitehouse_harvest-listing.csv \\
        data/www.obamawhitehouse/www.obamawhitehouse_harvest-nav.csv
"""

import argparse
import csv
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-o', '--output', required=True, metavar='FILE',
                        help='output CSV path')
    parser.add_argument('inputs', nargs='+', metavar='FILE',
                        help='input CSV files to merge (in order)')
    args = parser.parse_args()

    fieldnames = None
    total = 0

    with open(args.output, 'w', newline='', encoding='utf-8-sig') as out_f:
        writer = None
        for path in args.inputs:
            with open(path, newline='', encoding='utf-8-sig') as in_f:
                reader = csv.DictReader(in_f)
                if fieldnames is None:
                    fieldnames = reader.fieldnames
                    writer = csv.DictWriter(out_f, fieldnames=fieldnames)
                    writer.writeheader()
                elif reader.fieldnames != fieldnames:
                    sys.exit(
                        f'error: columns in {path} do not match the first input file\n'
                        f'  expected: {fieldnames}\n'
                        f'  got:      {reader.fieldnames}'
                    )
                rows = list(reader)
                writer.writerows(rows)
                total += len(rows)
                print(f'  {len(rows):>6} rows  {path}')

    print(f'  {total:>6} rows total -> {args.output}')


if __name__ == '__main__':
    main()
