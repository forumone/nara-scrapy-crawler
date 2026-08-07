"""S3 push interface for archive_content_v2 documents.

This project's responsibility ends at uploading a site's converted JSONL
to S3; a downstream Lambda watches the bucket and handles indexing,
including any reconciliation against existing index contents. This
module never touches index contents itself.

Credentials come from boto3's default provider chain (real environment
variables first, then a shared credentials file). A gitignored .env,
loaded via python-dotenv with override=False, fills in only what the
environment doesn't already have - see .env.example for what it
configures.

Key convention: <source_site>/<source_site>.jsonl, one folder per site.
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
