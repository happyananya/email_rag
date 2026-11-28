"""Repository checks against a migrated PostgreSQL database.

Run with:
TEST_DATABASE_URL=postgresql://emailrag:emailrag@localhost:5433/emailrag pytest -q tests/integration
Each test runs in a transaction and rolls it back.
"""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from email_rag import repo


@pytest.fixture
def db(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run PostgreSQL integration tests")
    conn = psycopg.connect(url, row_factory=dict_row)
    conn.execute("BEGIN")
    monkeypatch.setattr(repo, "get_conn", lambda: conn)

    sub = f"integration-{uuid4()}"
    user = conn.execute(
        "INSERT INTO users (cognito_sub, email) VALUES (%s, %s) RETURNING *",
        (sub, f"{sub}@example.com"),
    ).fetchone()
    account = conn.execute(
        """INSERT INTO email_accounts (user_id, email_address, secret_arn)
           VALUES (%s, %s, %s) RETURNING *""",
        (user["id"], f"{sub}@example.com", "arn:test"),
    ).fetchone()
    try:
        yield conn, user, account
    finally:
        conn.rollback()
        conn.close()


def test_action_item_extraction_is_idempotent(db):
    conn, user, account = db
    item = {"description": "Run the smoke test", "owner": "Bob", "due_date": "2026-11-30"}

    first = repo.save_action_items(user["id"], account["id"], "thread-1", [item])
    second = repo.save_action_items(user["id"], account["id"], "thread-1", [item])

    assert first[0]["id"] == second[0]["id"]
    count = conn.execute(
        "SELECT count(*) AS count FROM action_items WHERE user_id = %s", (user["id"],)
    ).fetchone()["count"]
    assert count == 1


def test_summary_cache_invalidates_when_a_new_email_arrives(db):
    conn, user, account = db
    conn.execute(
        """INSERT INTO emails
           (user_id, account_id, provider_message_id, thread_id, s3_key, created_at)
           VALUES (%s, %s, 'message-1', 'thread-1', 'raw/1', now() - interval '1 minute')""",
        (user["id"], account["id"]),
    )
    saved = repo.save_summary(user["id"], account["id"], "thread-1", "Summary", "model-1")
    assert repo.latest_summary(user["id"], account["id"], "thread-1", "model-1")["id"] == saved["id"]

    conn.execute(
        """INSERT INTO emails
           (user_id, account_id, provider_message_id, thread_id, s3_key, created_at)
           VALUES (%s, %s, 'message-2', 'thread-1', 'raw/2', now() + interval '1 second')""",
        (user["id"], account["id"]),
    )
    assert repo.latest_summary(user["id"], account["id"], "thread-1", "model-1") is None
