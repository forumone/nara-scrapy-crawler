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

# A bare URL in full_text/teaser_text is the signature of a column swap
# (e.g. a hand-edited CSV with url and full_text transposed) - a real
# page's body text is never just a URL on its own.
_BARE_URL_RE = re.compile(r'^\s*https?://\S+\s*$')


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
        for field in ('full_text', 'teaser_text'):
            value = row.get(field) or ''
            if _BARE_URL_RE.match(value):
                problems.append(f"row {i}: {field} looks like a bare URL, possible column swap: {value!r}")
    if problems:
        raise ValidationError('\n'.join(problems))
