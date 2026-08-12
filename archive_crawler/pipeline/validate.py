"""Pre-index validation for a site's content CSV rows.

Narrower than ~/git/nara/scripts/validate-opensearch-csv.py (invisible-
unicode, HTML-tag, HTML-entity, missing-space, "Continue reading" checks)
- that script audits CSVs already pulled back out of the live index; this
one only gates whether a row is safe to index at all. Extending this
validator with that check set is a reasonable follow-up, not part of this
module.
"""
import re

from archive_crawler.pipeline import registry

_URL_RE = re.compile(r'^https?://\S+$')


class ValidationError(ValueError):
    pass


def validate_rows(rows):
    """Raise ValidationError listing every problem found across all rows -
    not just the first - so an operator sees everything to fix in one
    pass. Row numbers are 1-indexed against the CSV including its header
    (so the first data row is row 2, matching what a spreadsheet/editor
    would show)."""
    allowed_source_sites = {info.source_site for info in registry.list_sites().values()}
    problems = []
    for i, row in enumerate(rows, start=2):
        source_site = row.get('source_site', '')
        if source_site not in allowed_source_sites:
            problems.append(f"row {i}: unknown source_site {source_site!r}")
        url = row.get('url') or ''
        if not _URL_RE.match(url):
            problems.append(f"row {i}: url is missing or malformed (becomes the OpenSearch document ID): {url!r}")
    if problems:
        raise ValidationError('\n'.join(problems))
