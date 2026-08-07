"""S3 push interface for archive_content_v2 documents.

This project's responsibility ends at uploading a site's converted JSONL
to S3. A downstream Lambda (closer to the OpenSearch side of the
pipeline) watches that bucket for new/updated .jsonl files and handles
indexing itself, including whatever reconciliation against existing
index contents it needs - deleting and re-indexing a source_site's stale
documents, for example. This project does not do that reconciliation
and never deletes or otherwise touches index contents directly.

Credentials: boto3's own default provider chain already checks real
environment variables (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/
AWS_SESSION_TOKEN) before falling back to a shared credentials file, so
loading a gitignored .env with python-dotenv's default override=False
reproduces that same "real environment wins" behavior for free: a value
already present in the environment is left untouched, and only a value
.env defines that the environment doesn't already have gets set. See
.env.example for what .env can configure - a fallback credentials file
location/profile, plus the target bucket/region/prefix.

Key convention: <source_site>/<source_site>.jsonl, one folder per site,
matching nara-crawl-data's existing layout. How id/document_type/source/
changed should be populated on each document (see convert.py) is still
open - it doesn't block this module's own upload logic.
"""
import logging
import os

import boto3
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(override=False)


def _bucket_and_key(source_site):
    bucket = os.environ.get('NARA_S3_BUCKET')
    if not bucket:
        raise RuntimeError(
            "NARA_S3_BUCKET is not set. Copy .env.example to .env and fill "
            "it in, or export NARA_S3_BUCKET directly in the environment."
        )
    prefix = os.environ.get('NARA_S3_PREFIX', '').strip('/')
    key = f'{source_site}/{source_site}.jsonl'
    if prefix:
        key = f'{prefix}/{key}'
    return bucket, key


def push(source_site, jsonl_path, doc_count):
    """Upload source_site's converted JSONL to S3."""
    bucket, key = _bucket_and_key(source_site)
    client = boto3.client('s3', region_name=os.environ.get('AWS_DEFAULT_REGION'))
    client.upload_file(jsonl_path, bucket, key)
    logger.info(
        "Pushed %d document(s) for source_site=%s from %s to s3://%s/%s",
        doc_count, source_site, jsonl_path, bucket, key,
    )
