"""S3 storage for raw MIME bodies, under a per-user prefix."""

import boto3

from email_rag.config import settings

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def raw_email_key(user_id: str, account_id: str, message_id: str) -> str:
    return f"users/{user_id}/accounts/{account_id}/messages/{message_id}.eml"


def put_raw_email(key: str, raw: bytes, user_id: str) -> None:
    # Encrypted at rest by the bucket's default SSE-KMS key. Tenant scoping is by key prefix;
    # see docs/architecture.md "Per-tenant encryption" for the per-tenant KMS key follow-up.
    _client().put_object(
        Bucket=settings().email_bucket,
        Key=key,
        Body=raw,
        ContentType="message/rfc822",
        Metadata={"tenant": user_id},
    )


def get_raw_email(key: str) -> bytes:
    return _client().get_object(Bucket=settings().email_bucket, Key=key)["Body"].read()


def delete_prefix(prefix: str) -> None:
    bucket = settings().email_bucket
    paginator = _client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            _client().delete_objects(Bucket=bucket, Delete={"Objects": objs})

