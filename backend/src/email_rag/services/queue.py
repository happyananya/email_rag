"""Enqueue message ids onto the ingestion SQS queue."""

import json

import boto3

from email_rag.config import settings

_sqs = None
MAX_BATCH_ATTEMPTS = 3


def enqueue_messages(account_id: str, message_ids: list[str]) -> int:
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs")
    url = settings().ingest_queue_url
    for i in range(0, len(message_ids), 10):  # SQS batch limit
        batch = message_ids[i : i + 10]
        pending = [
            {"Id": str(n), "MessageBody": json.dumps({"account_id": account_id, "message_id": m})}
            for n, m in enumerate(batch)
        ]
        for _attempt in range(MAX_BATCH_ATTEMPTS):
            response = _sqs.send_message_batch(QueueUrl=url, Entries=pending)
            failed = response.get("Failed", [])
            if not failed:
                break
            permanent = [item for item in failed if item.get("SenderFault")]
            if permanent:
                raise RuntimeError(f"SQS rejected ingestion messages: {permanent}")
            failed_ids = {item["Id"] for item in failed}
            pending = [item for item in pending if item["Id"] in failed_ids]
        else:
            raise RuntimeError(f"SQS ingestion batch still failed after retries: {failed}")
    return len(message_ids)
