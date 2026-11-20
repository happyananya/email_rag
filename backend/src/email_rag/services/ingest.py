"""Shared ingestion step: fetch one Gmail message, store raw in S3, parse, chunk, embed, index."""

import logging
from datetime import UTC, datetime

from email_rag import repo
from email_rag.services import chunking, embeddings, storage
from email_rag.services.gmail import GmailClient
from email_rag.services.mime import parse_raw

log = logging.getLogger(__name__)


def ingest_message(account: dict, gmail: GmailClient, message_id: str) -> str | None:
    user_id, account_id = str(account["user_id"]), str(account["id"])
    msg = gmail.get_message(message_id)

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
    if email_id is None:
        log.info("message %s already ingested", message_id)
        return None

    chunks = chunking.chunk_email(parsed)
    vectors = embeddings.embed_many(chunks)
    repo.insert_chunks(user_id, account_id, email_id, list(zip(chunks, vectors, strict=True)))
    return email_id
