"""CSV row -> archive_content_v2 OpenSearch document.

id/document_type/source/changed aren't populated here - no document from
any of the 14 archive sites currently exists in the live index to
reference their shape (see the pipeline plan's open questions). Those
fields are left for push.py once that's answered, not faked here.

last_seen_at IS populated here, one identical value per rows_to_jsonl
call shared by every row in the file, tombstones included - the
naraCrawlIngestor Lambda uses it to gate freshness per source_site
during reconciliation.

rows_to_jsonl also accepts tombstone_urls: a list of URLs confirmed
gone this run (crawl_health.find_confirmed_deletions - a plain http_404
in the site's dropped-log), each written as a delete-marker row via
to_tombstone rather than a content row via to_document. This is what
lets the Lambda delete a source_site's removed URLs explicitly instead
of inferring deletion from a URL's plain absence from the file, which
cannot tell a confirmed 404 apart from a URL this run simply failed to
reach because of a transient network or server error - see
crawl_health.py's module docstring and ABORT_CONDITIONS.md.
"""
import json
import os
from datetime import datetime, timezone

# CSV column -> live OpenSearch field. source_type maps to source_type_id,
# not source_type - items.py's own comment describing the CSV schema as
# matching the OpenSearch mapping is wrong on this one field. warnings has
# no live field at all and is intentionally dropped.
_FIELD_MAP = {
    'url': 'url',
    'title': 'title',
    'teaser_text': 'teaser_text',
    'full_text': 'full_text',
    'source_site': 'source_site',
    'source_type': 'source_type_id',
}


def to_document(row, last_seen_at):
    doc = {opensearch_field: row.get(csv_field, '') for csv_field, opensearch_field in _FIELD_MAP.items()}
    doc['last_seen_at'] = last_seen_at
    return doc


def to_tombstone(url, source_site, last_seen_at):
    """A delete-marker row for a URL crawl_health.find_confirmed_deletions
    found confirmed gone (a plain http_404) this run. _tombstone is the
    naraCrawlIngestor Lambda's signal to delete this url's document
    outright instead of upserting it - see rows_to_jsonl's docstring and
    convert.py's module docstring for why absence alone can't carry this
    meaning."""
    return {
        'url': url,
        'source_site': source_site,
        'last_seen_at': last_seen_at,
        '_tombstone': True,
    }


def rows_to_jsonl(rows, out_path, last_seen_at=None, tombstone_urls=None, source_site=None):
    """Write one JSON document per line to out_path, creating its parent
    directory if needed. Every row gets the same last_seen_at - generated
    once here (UTC, matching the live index's existing convention, e.g.
    "2026-07-15T17:01:14Z") unless the caller passes one in.

    tombstone_urls (optional) adds one to_tombstone delete-marker row per
    URL, after every row's content document. source_site is required
    whenever tombstone_urls is non-empty - the dropped-log entries
    find_confirmed_deletions reads from carry only a url and a reason,
    not a source_site, so the caller (which already knows which site it
    is pushing) supplies it here instead.

    Returns (rows_written, tombstones_written)."""
    if last_seen_at is None:
        last_seen_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    if tombstone_urls and not source_site:
        raise ValueError('source_site is required when tombstone_urls is non-empty')
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    count = 0
    tombstone_count = 0
    with open(out_path, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(to_document(row, last_seen_at), ensure_ascii=False))
            f.write('\n')
            count += 1
        for url in tombstone_urls or []:
            f.write(json.dumps(to_tombstone(url, source_site, last_seen_at), ensure_ascii=False))
            f.write('\n')
            tombstone_count += 1
    return count, tombstone_count
