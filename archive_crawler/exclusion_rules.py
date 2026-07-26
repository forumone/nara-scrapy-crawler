"""Per-domain URL exclusion rules, loaded from committed YAML files.

Replaces the hardcoded per-spider if/elif URL-pattern filters, the shared
extension allowlist, and generic_crawl_harvest's constants with a single
data-driven mechanism. See url-exclusion-rules-yaml-plan.md for the design.

Rule files live at archive_crawler/exclusion_rules/<source_site>.yml, one
per domain, structured as:

    extensions:
      mode: allow            # allow | deny
      values: [html, htm, php, asp, aspx, shtml, cfm, cgi]

    rules:                   # evaluated in order, first match wins
      - match: contains       # contains | regex | url_list
        pattern: "/images/"
        reason: "url_pattern:/images/"
      - match: regex
        pattern: '\\.v\\.html$'
        reason: "url_pattern:.v.html"
      - match: url_list        # exact-URL membership - for a known, finite,
        values:                 # non-pattern-shaped set of URLs (e.g. every
          - "https://example.com/page-one"   # item a listing walk found,
          - "https://example.com/page-two"   # rather than a path shape)
        reason: "some_reason"

    nav_deny:                 # regex patterns for NavHarvesterMixin's Rule(deny=...)
      - '/sites/'

    pagination:                # generic_crawl_harvest: follow-but-don't-record patterns
      - '\\?page='

    query_params_allow:        # generic_crawl_harvest: query-string keep-list
      - page
"""
import os
import re

import yaml

RULES_DIR = os.path.join(os.path.dirname(__file__), 'exclusion_rules')

_DEFAULT_EXTENSIONS = {
    'mode': 'allow',
    'values': ['html', 'htm', 'php', 'asp', 'aspx', 'shtml', 'cfm', 'cgi'],
}


class ExclusionRules:
    """Loaded, merged rule set for one domain. Immutable once constructed."""

    def __init__(self, extensions=None, rules=None, nav_deny=None,
                 pagination=None, query_params_allow=None):
        self.extensions = extensions or dict(_DEFAULT_EXTENSIONS)
        self.rules = rules or []
        self.nav_deny = nav_deny or []
        self.pagination = pagination or []
        self.query_params_allow = query_params_allow or []


def _rule_file_path(source_site):
    return os.path.join(RULES_DIR, f'{source_site}.yml')


def _read_yaml(path):
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data


def _rules_from_dict(data):
    rules = list(data.get('rules') or [])
    for entry in rules:
        # Converted once at load time (cached per-spider, see
        # _spider_exclusion_rules), not per-URL - a url_list rule can hold
        # hundreds of entries, and repeated `in` on a list would be O(n) per
        # check across every URL a crawl considers.
        if entry.get('match') == 'url_list':
            entry['values'] = set(entry.get('values') or [])
    return ExclusionRules(
        extensions=data.get('extensions') or dict(_DEFAULT_EXTENSIONS),
        rules=rules,
        nav_deny=list(data.get('nav_deny') or []),
        pagination=list(data.get('pagination') or []),
        query_params_allow=list(data.get('query_params_allow') or []),
    )


def load_rules(source_site, override_path=None, mode='append'):
    """Load the committed rules file for source_site, optionally overlaying
    override_path per mode:

    - 'append': union of committed + override rules/nav_deny/pagination/
      query_params_allow (extensions from override replace the committed
      ones if given). Neither the committed file nor override_path is
      written to - this is a runtime-only merge.
    - 'replace': override_path's rules entirely replace the committed
      file's for every section that override_path defines; sections it
      omits fall back to the committed file's.
    """
    committed_path = _rule_file_path(source_site)
    base = _rules_from_dict(_read_yaml(committed_path)) if os.path.exists(committed_path) else ExclusionRules()

    if not override_path:
        return base

    override = _rules_from_dict(_read_yaml(override_path))

    if mode == 'replace':
        return ExclusionRules(
            extensions=override.extensions or base.extensions,
            rules=override.rules or base.rules,
            nav_deny=override.nav_deny or base.nav_deny,
            pagination=override.pagination or base.pagination,
            query_params_allow=override.query_params_allow or base.query_params_allow,
        )
    if mode == 'append':
        return ExclusionRules(
            extensions=override.extensions or base.extensions,
            rules=base.rules + override.rules,
            nav_deny=base.nav_deny + override.nav_deny,
            pagination=base.pagination + override.pagination,
            query_params_allow=base.query_params_allow + override.query_params_allow,
        )
    raise ValueError(f"mode must be 'append' or 'replace', got {mode!r}")


def is_web_url(url, rules):
    """Return True if url looks like a web page rather than a downloadable asset.

    Rules, applied in order:
    1. No dot in the last path segment -> no extension -> allow.
    2. "Extension" longer than 4 characters -> not a real extension -> allow.
    3. Extension matches rules.extensions per its mode (allow: must be listed;
       deny: must NOT be listed).
    """
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip('/')
    last_segment = path.rsplit('/', 1)[-1] if path else ''
    if '.' not in last_segment:
        return True
    ext = last_segment.rsplit('.', 1)[-1].lower()
    if len(ext) > 4:
        return True
    values = set(v.lower() for v in rules.extensions.get('values', []))
    if rules.extensions.get('mode', 'allow') == 'deny':
        return ext not in values
    return ext in values


def _matches(entry, url):
    if entry['match'] == 'contains':
        return entry['pattern'] in url
    if entry['match'] == 'regex':
        return re.search(entry['pattern'], url) is not None
    if entry['match'] == 'url_list':
        return url in entry['values']
    raise ValueError(f"unknown match kind {entry['match']!r} in rule {entry!r}")


def match_exclude(url, rules):
    """Return the reason string of the first matching rule, or None."""
    for entry in rules.rules:
        if _matches(entry, url):
            return entry['reason']
    return None


def nav_deny_patterns(rules):
    return tuple(rules.nav_deny)


def pagination_patterns(rules):
    return tuple(rules.pagination)


def allowed_query_params(rules):
    return set(rules.query_params_allow)
