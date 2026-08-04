"""Per-source_site warning-based row filtering, applied before conversion.

See project memory project_warnings_column_plan for the warnings column
itself (no_body/no_title/short_body). A row is dropped only when its full
warnings set is a SUPERSET of the site's configured filter set below - a
two-label filter entry requires both labels present on that row, not
either alone.
"""

# {source_site: frozenset of warning labels that, ALL present together on
# one row, drop it}. A source_site absent from this table is a
# configuration error, not a default to fall back on - most sites already
# filter no_body in some form, so a silent default is more likely wrong
# than requiring one explicit line per new site.
_FILTER_SETS = {
    'open.obamawhitehouse': frozenset(),
    'petitions.obamawhitehouse': frozenset(),
    'petitions.trumpwhitehouse': frozenset(),
    'clintonwhitehouse1': frozenset({'no_body'}),
    'clintonwhitehouse2': frozenset({'no_body'}),
    'clintonwhitehouse3': frozenset({'no_body'}),
    'clintonwhitehouse4': frozenset({'no_body'}),
    'clintonwhitehouse5': frozenset({'no_body'}),
    'clintonwhitehouse6': frozenset({'no_body'}),
    'letsmove.obamawhitehouse': frozenset({'no_body', 'no_title'}),
    'www.bidenwhitehouse': frozenset({'no_body', 'no_title'}),
    'www.georgewbush-whitehouse': frozenset({'no_body', 'no_title'}),
    'www.obamawhitehouse': frozenset({'no_body', 'no_title'}),
    'www.trumpwhitehouse': frozenset({'no_body', 'no_title'}),
}


class UnknownSiteFilterError(ValueError):
    pass


def _row_warnings(row):
    raw = row.get('warnings') or ''
    return frozenset(w.strip() for w in raw.split(',') if w.strip())


def filter_rows(rows, source_site):
    """Return (kept, dropped). Raises UnknownSiteFilterError if
    source_site has no entry in _FILTER_SETS at all."""
    if source_site not in _FILTER_SETS:
        raise UnknownSiteFilterError(
            f"no filter_rows entry for source_site {source_site!r} - add one to "
            f"_FILTER_SETS rather than assume a default"
        )
    filter_set = _FILTER_SETS[source_site]
    if not filter_set:
        return list(rows), []
    kept, dropped = [], []
    for row in rows:
        (dropped if filter_set <= _row_warnings(row) else kept).append(row)
    return kept, dropped
