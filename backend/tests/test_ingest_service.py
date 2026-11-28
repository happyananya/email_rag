from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest

from email_rag.services import ingest


def _message() -> dict:
    raw = EmailMessage()
    raw["Subject"] = "Status"
    raw["From"] = "alice@example.com"
    raw["To"] = "bob@example.com"
    raw.set_content("The deployment is ready.")
    return {
        "raw": raw.as_bytes(),
        "internalDate": "1795600000000",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "snippet": "The deployment is ready.",
    }


class _Gmail:
    def get_message(self, _message_id):
        return _message()


class _FixtureGmail:
    def __init__(self, raw: bytes):
        self.raw = raw

    def get_message(self, message_id):
        return {
            "raw": self.raw,
            "internalDate": "1795788900000",
            "threadId": f"thread-{message_id}",
            "labelIds": ["INBOX"],
            "snippet": "Fixture message",
        }


class _DeletedMessageGmail:
    def get_message(self, message_id):
        request = httpx.Request("GET", f"https://gmail.googleapis.com/messages/{message_id}")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("message not found", request=request, response=response)


def _patch_storage_and_repo(monkeypatch, chunk_count: int):
    monkeypatch.setattr(ingest.storage, "put_raw_email", lambda *_args: None)
    monkeypatch.setattr(ingest.storage, "raw_email_key", lambda *_args: "raw/message.eml")
    monkeypatch.setattr(ingest.repo, "insert_email", lambda **_kwargs: "email-1")
    monkeypatch.setattr(ingest.repo, "count_email_chunks", lambda *_args: chunk_count)


def test_complete_email_retry_skips_embedding(monkeypatch):
    _patch_storage_and_repo(monkeypatch, chunk_count=1)
    monkeypatch.setattr(
        ingest.embeddings,
        "embed_many",
        lambda _chunks: (_ for _ in ()).throw(AssertionError("should not re-embed")),
    )

    result = ingest.ingest_message({"user_id": "user-1", "id": "account-1"}, _Gmail(), "msg-1")

    assert result == "email-1"


def test_partial_email_retry_fills_missing_chunks(monkeypatch):
    _patch_storage_and_repo(monkeypatch, chunk_count=0)
    monkeypatch.setattr(ingest.embeddings, "embed_many", lambda chunks: [[0.1] for _ in chunks])
    inserted = []
    monkeypatch.setattr(ingest.repo, "insert_chunks", lambda *args: inserted.append(args))

    result = ingest.ingest_message({"user_id": "user-1", "id": "account-1"}, _Gmail(), "msg-1")

    assert result == "email-1"
    assert inserted
    assert inserted[0][2] == "email-1"
    assert inserted[0][3][0][1] == [0.1]


def test_deleted_gmail_message_is_skipped_without_retrying_storage(monkeypatch):
    monkeypatch.setattr(
        ingest.storage,
        "put_raw_email",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not store a deleted message")),
    )

    result = ingest.ingest_message(
        {"user_id": "user-1", "id": "account-1"}, _DeletedMessageGmail(), "deleted-1"
    )

    assert result is None


@pytest.mark.parametrize(
    ("filename", "expected_subject", "has_html"),
    [
        ("plain_message.eml", "Deployment checklist", False),
        ("html_message.eml", "Design review notes", True),
    ],
)
def test_eml_corpus_flows_through_ingestion(monkeypatch, filename, expected_subject, has_html):
    raw = (Path(__file__).parent / "fixtures" / filename).read_bytes()
    monkeypatch.setattr(ingest.storage, "put_raw_email", lambda *_args: None)
    monkeypatch.setattr(ingest.storage, "raw_email_key", lambda *_args: f"raw/{filename}")
    inserted_email = {}

    def insert_email(**kwargs):
        inserted_email.update(kwargs)
        return "email-1"

    monkeypatch.setattr(ingest.repo, "insert_email", insert_email)
    monkeypatch.setattr(ingest.repo, "count_email_chunks", lambda *_args: 0)
    monkeypatch.setattr(ingest.embeddings, "embed_many", lambda chunks: [[0.1] for _ in chunks])
    inserted_chunks = []
    monkeypatch.setattr(ingest.repo, "insert_chunks", lambda *args: inserted_chunks.extend(args[3]))

    result = ingest.ingest_message(
        {"user_id": "user-1", "id": "account-1"}, _FixtureGmail(raw), filename
    )

    assert result == "email-1"
    assert inserted_email["subject"] == expected_subject
    assert inserted_email["s3_key"] == f"raw/{filename}"
    assert inserted_chunks
    combined = "\n".join(text for text, _vector in inserted_chunks)
    assert expected_subject in combined
    assert ("review is complete" in combined) is has_html
