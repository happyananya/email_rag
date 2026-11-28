"""Shared ingestion step: fetch one Gmail message, store raw in S3, parse, chunk, embed, index."""

import logging
from datetime import UTC, datetime

import httpx

from email_rag import repo
from email_rag.services import chunking, embeddings, storage
from email_rag.services.gmail import GmailClient
from email_rag.services.mime import parse_raw

log = logging.getLogger(__name__)


def ingest_message(account: dict, gmail: GmailClient, message_id: str) -> str | None:
    user_id, account_id = str(account["user_id"]), str(account["id"])
    try:
        msg = gmail.get_message(message_id)
    except httpx.HTTPStatusError as exc:
        # A message can be deleted after Gmail returns its id from history/list. Retrying cannot
        # recover it and would only send a harmless stale id to the DLQ.
        if exc.response.status_code == 404:
            log.info("message %s no longer exists; skipping", message_id)
            return None
        raise

    key = storage.raw_email_key(user_id, account_id, message_id)
    storage.put_raw_email(key, msg["raw"], user_id)

    parsed = parse_raw(msg["raw"])
    sent_at = parsed.sent_at or datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=UTC)
    parsed.sent_at = sent_at

    email_id = repo.insert_email(
        user_id=user_id,
        account_id=account_id,
        provider_message_id=message_id,
        thread_id=msg["threadId"],
        subject=parsed.subject,
        sender=parsed.sender,
        recipients=parsed.recipients,
        sent_at=sent_at,
        snippet=msg.get("snippet"),
        labels=msg.get("labelIds", []),
        s3_key=key,
    )
    chunks = chunking.chunk_email(parsed)
    if repo.count_email_chunks(user_id, account_id, email_id) >= len(chunks):
        log.info("message %s already fully indexed", message_id)
        return email_id

    # insert_chunks is conflict-safe, so a retry can fill any chunks left by a partial failure.
    vectors = embeddings.embed_many(chunks)
    repo.insert_chunks(user_id, account_id, email_id, list(zip(chunks, vectors, strict=True)))
    return email_id
