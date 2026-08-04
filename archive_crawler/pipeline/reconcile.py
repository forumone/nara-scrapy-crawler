"""Push interface for archive_content_v2 documents - a dry-run-only stub.

No AWS calls: nara-opensearch-lambda's delete/upsert support, its S3 watch
location, the AWS access this utility would need, and how id/
document_type/source/changed should be populated are all unconfirmed (see
the NAD2-756 pipeline plan's open questions). None of this pipeline's
other modules depend on those answers - only this one does.

The live archive_content_v2 mapping's last_seen_at/last_seen_run_id fields
are shaped for a watermark-based reconcile (stamp every doc from a run
with that run's ID, then delete anything for the same source_site
carrying a stale watermark) rather than a blind delete-then-insert - worth
raising once the open questions are answered; this stub doesn't resolve
them on its own.
"""
import logging

logger = logging.getLogger(__name__)


def push(source_site, jsonl_path, doc_count):
    """Log what a real push would do; make no network call."""
    logger.info(
        "[dry-run] would push %d document(s) for source_site=%s from %s to "
        "OpenSearch (no AWS call made - reconcile.py is a stub; see the "
        "NAD2-756 pipeline plan's open questions)",
        doc_count, source_site, jsonl_path,
    )
