"""Enqueue message ids onto the ingestion SQS queue."""

import json

import boto3

from email_rag.config import settings

_sqs = None


def enqueue_messages(account_id: str, message_ids: list[str]) -> int:
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs")
    url = settings().ingest_queue_url
    for i in range(0, len(message_ids), 10):  # SQS batch limit
        batch = message_ids[i : i + 10]
        _sqs.send_message_batch(
            QueueUrl=url,
            Entries=[
                {"Id": str(n), "MessageBody": json.dumps({"account_id": account_id, "message_id": m})}
                for n, m in enumerate(batch)
            ],
        )
    return len(message_ids)
