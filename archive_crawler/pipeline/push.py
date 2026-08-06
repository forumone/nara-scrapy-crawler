"""S3 push interface for archive_content_v2 documents - a dry-run-only stub.

This project's responsibility ends at uploading a site's converted JSONL
to S3. A downstream Lambda (closer to the OpenSearch side of the
pipeline) watches that bucket for new/updated .jsonl files and handles
indexing itself, including whatever reconciliation against existing
index contents it needs - deleting and re-indexing a source_site's stale
documents, for example. This project does not do that reconciliation
and never deletes or otherwise touches index contents directly.

No AWS calls yet: the S3 bucket/prefix that Lambda watches, the AWS
access this utility needs (S3 write only - no OpenSearch access at all,
since this project doesn't touch the index), and how id/document_type/
source/changed should be populated on each archive_content_v2 document
are all unconfirmed. None of this pipeline's other modules depend on
those answers - only this one does.
"""
import logging

logger = logging.getLogger(__name__)


def push(source_site, jsonl_path, doc_count):
    """Log what a real push would do; make no network call."""
    logger.info(
        "[dry-run] would push %d document(s) for source_site=%s from %s to "
        "S3 (no AWS call made - push.py is a stub; see the NAD2-756 "
        "pipeline plan's open questions)",
        doc_count, source_site, jsonl_path,
    )
