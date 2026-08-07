"""Per-source_site warning-based row filtering (no_body/no_title/
short_body warnings), applied before conversion. A row is dropped only
when its full warnings set is a superset of the site's configured filter
set - a two-label filter entry requires both labels present, not either
alone.

Config lives at archive_crawler/filter_rules/<source_site>.yml, one file
per site (separate from exclusion_rules.py's per-domain rules, which
cover crawl-time URL exclusion rather than this module's index-time
warning-filtering):

    drop_if_all_present: [no_body]     # or [] for "never drop"

A source_site with no committed file is a configuration error, not a
default to fall back on.

load_filter_set's override_path/mode overlay a per-run override on top
of the committed file: 'append' unions the override's
drop_if_all_present into the committed list (only ever more
restrictive); 'replace' uses the override's own value if it defines the
key, else falls back to the committed file's.
"""
import os

import yaml

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILTER_RULES_DIR = os.path.join(_PACKAGE_ROOT, 'filter_rules')


class UnknownSiteFilterError(ValueError):
    pass


def _rule_file_path(source_site):
    return os.path.join(FILTER_RULES_DIR, f'{source_site}.yml')


def _read_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_filter_set(source_site, override_path=None, mode='append'):
    """Return the frozenset of warning labels that, ALL present together
    on one row, drop it for source_site. Raises UnknownSiteFilterError if
    no committed archive_crawler/filter_rules/<source_site>.yml exists."""
    committed_path = _rule_file_path(source_site)
    if not os.path.exists(committed_path):
        raise UnknownSiteFilterError(
            f"no filter_rules/{source_site}.yml found - create one "
            f"(even an empty 'drop_if_all_present: []' for \"never drop\") "
            f"rather than assume a default"
        )
    committed = frozenset(_read_yaml(committed_path).get('drop_if_all_present') or [])

    if not override_path:
        return committed

    override_data = _read_yaml(override_path)
    if mode == 'replace':
        if 'drop_if_all_present' in override_data:
            return frozenset(override_data['drop_if_all_present'] or [])
        return committed
    if mode == 'append':
        return committed | frozenset(override_data.get('drop_if_all_present') or [])
    raise ValueError(f"mode must be 'append' or 'replace', got {mode!r}")


def _row_warnings(row):
    raw = row.get('warnings') or ''
    return frozenset(w.strip() for w in raw.split(',') if w.strip())


def filter_rows(rows, source_site, override_path=None, mode='append'):
    """Return (kept, dropped)."""
    filter_set = load_filter_set(source_site, override_path, mode)
    if not filter_set:
        return list(rows), []
    kept, dropped = [], []
    for row in rows:
        (dropped if filter_set <= _row_warnings(row) else kept).append(row)
    return kept, dropped
