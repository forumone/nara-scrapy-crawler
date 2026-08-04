"""CSV row -> archive_content_v2 OpenSearch document.

id/document_type/source/changed aren't populated here - no document from
any of the 14 archive sites currently exists in the live index to
reference their shape (see the pipeline plan's open questions). Those
fields are left for reconcile.py once that's answered, not faked here.
"""
import json
import os

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


def to_document(row):
    return {opensearch_field: row.get(csv_field, '') for csv_field, opensearch_field in _FIELD_MAP.items()}


def rows_to_jsonl(rows, out_path):
    """Write one JSON document per line to out_path, creating its parent
    directory if needed. Returns the number of documents written."""
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    count = 0
    with open(out_path, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(to_document(row), ensure_ascii=False))
            f.write('\n')
            count += 1
    return count
