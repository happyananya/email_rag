"""Data access. Every tenant-scoped function takes user_id and filters on it (tenant isolation)."""

from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from email_rag.db import get_conn

Row = dict[str, Any]


# --- users -----------------------------------------------------------------

def upsert_user(cognito_sub: str, email: str) -> Row:
    return get_conn().execute(
        """INSERT INTO users (cognito_sub, email) VALUES (%s, %s)
           ON CONFLICT (cognito_sub) DO UPDATE SET email = EXCLUDED.email
           RETURNING *""",
        (cognito_sub, email),
    ).fetchone()


# --- accounts --------------------------------------------------------------

def create_account(user_id: str, email_address: str, secret_arn: str) -> Row:
    return get_conn().execute(
        """INSERT INTO email_accounts (user_id, email_address, secret_arn)
           VALUES (%s, %s, %s)
           ON CONFLICT (user_id, email_address)
           DO UPDATE SET secret_arn = EXCLUDED.secret_arn, status = 'backfilling'
           RETURNING *""",
        (user_id, email_address, secret_arn),
    ).fetchone()


def list_accounts(user_id: str) -> list[Row]:
    return get_conn().execute(
        """SELECT id, provider, email_address, status, last_synced_at
           FROM email_accounts WHERE user_id = %s ORDER BY created_at""",
        (user_id,),
    ).fetchall()


def get_account(user_id: str, account_id: str) -> Row | None:
    return get_conn().execute(
        "SELECT * FROM email_accounts WHERE id = %s AND user_id = %s", (account_id, user_id)
    ).fetchone()


def delete_account(user_id: str, account_id: str) -> None:
    get_conn().execute(
        "DELETE FROM email_accounts WHERE id = %s AND user_id = %s", (account_id, user_id)
    )


# System-level lookups used by the sync pipeline (not reachable from the user API).

def get_account_by_id(account_id: str) -> Row | None:
    return get_conn().execute(
        "SELECT * FROM email_accounts WHERE id = %s", (account_id,)
    ).fetchone()


def get_accounts_by_email(email_address: str) -> list[Row]:
    return get_conn().execute(
        "SELECT * FROM email_accounts WHERE email_address = %s AND status = 'active'",
        (email_address,),
    ).fetchall()


def list_active_accounts() -> list[Row]:
    return get_conn().execute(
        "SELECT * FROM email_accounts WHERE status = 'active'"
    ).fetchall()


def update_sync_state(
    account_id: str,
    *,
    history_id: str | None = None,
    status: str | None = None,
    watch_expiration: datetime | None = None,
) -> None:
    get_conn().execute(
        """UPDATE email_accounts SET
             history_id = COALESCE(%s, history_id),
             status = COALESCE(%s, status),
             watch_expiration = COALESCE(%s, watch_expiration),
             last_synced_at = now()
           WHERE id = %s""",
        (history_id, status, watch_expiration, account_id),
    )


# --- emails & chunks -------------------------------------------------------

def insert_email(
    *,
    user_id: str,
    account_id: str,
    provider_message_id: str,
    thread_id: str,
    subject: str | None,
    sender: str | None,
    recipients: list[str],
    sent_at: datetime | None,
    snippet: str | None,
    labels: list[str],
    s3_key: str,
) -> str:
    """Upsert email metadata and return its id so interrupted ingestion can resume."""
    row = get_conn().execute(
        """INSERT INTO emails (user_id, account_id, provider_message_id, thread_id, subject,
                               sender, recipients, sent_at, snippet, labels, s3_key)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (account_id, provider_message_id) DO UPDATE SET
             thread_id = EXCLUDED.thread_id,
             subject = EXCLUDED.subject,
             sender = EXCLUDED.sender,
             recipients = EXCLUDED.recipients,
             sent_at = EXCLUDED.sent_at,
             snippet = EXCLUDED.snippet,
             labels = EXCLUDED.labels,
             s3_key = EXCLUDED.s3_key
           RETURNING id""",
        (user_id, account_id, provider_message_id, thread_id, subject, sender,
         Jsonb(recipients), sent_at, snippet, labels, s3_key),
    ).fetchone()
    return str(row["id"])


def count_email_chunks(user_id: str, account_id: str, email_id: str) -> int:
    """Return the indexed chunk count, preserving tenant isolation on retry checks."""
    row = get_conn().execute(
        """SELECT count(*) AS count FROM email_chunks
           WHERE user_id = %s AND account_id = %s AND email_id = %s""",
        (user_id, account_id, email_id),
    ).fetchone()
    return int(row["count"])


def insert_chunks(
    user_id: str, account_id: str, email_id: str, chunks: list[tuple[str, list[float]]]
) -> None:
    with get_conn().cursor() as cur:
        cur.executemany(
            """INSERT INTO email_chunks (user_id, account_id, email_id, chunk_index, content, embedding)
               VALUES (%s, %s, %s, %s, %s, %s::vector)
               ON CONFLICT (email_id, chunk_index) DO NOTHING""",
            [(user_id, account_id, email_id, i, text, emb) for i, (text, emb) in enumerate(chunks)],
        )


def list_threads(user_id: str, account_id: str, limit: int = 50, before: datetime | None = None):
    return get_conn().execute(
        """SELECT * FROM (
             SELECT DISTINCT ON (thread_id) thread_id, id AS email_id, subject, sender, sent_at,
                    snippet
             FROM emails
             WHERE user_id = %s AND account_id = %s
             ORDER BY thread_id, sent_at DESC
           ) latest
           WHERE (%s::timestamptz IS NULL OR sent_at < %s)
           ORDER BY sent_at DESC
           LIMIT %s""",
        (user_id, account_id, before, before, limit),
    ).fetchall()


def get_thread_emails(user_id: str, account_id: str, thread_id: str) -> list[Row]:
    return get_conn().execute(
        """SELECT * FROM emails WHERE user_id = %s AND account_id = %s AND thread_id = %s
           ORDER BY sent_at""",
        (user_id, account_id, thread_id),
    ).fetchall()


def search_chunks(
    user_id: str, embedding: list[float], top_k: int, account_id: str | None = None
) -> list[Row]:
    """Top-k cosine similarity search, always filtered by tenant (and optionally account)."""
    return get_conn().execute(
        """SELECT c.content, c.email_id, e.subject, e.sender, e.sent_at, e.thread_id,
                  e.account_id, 1 - (c.embedding <=> %s::vector) AS score
           FROM email_chunks c JOIN emails e ON e.id = c.email_id
           WHERE c.user_id = %s AND (%s::uuid IS NULL OR c.account_id = %s::uuid)
           ORDER BY c.embedding <=> %s::vector
           LIMIT %s""",
        (embedding, user_id, account_id, account_id, embedding, top_k),
    ).fetchall()


# --- AI results ------------------------------------------------------------

def save_summary(user_id: str, account_id: str, thread_id: str, content: str, model: str) -> Row:
    return get_conn().execute(
        """INSERT INTO summaries (user_id, account_id, thread_id, content, model)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (user_id, account_id, thread_id, content, model),
    ).fetchone()


def latest_summary(
    user_id: str, account_id: str, thread_id: str, model: str | None = None
) -> Row | None:
    """Return a cached summary only when it matches the model and no newer email was ingested."""
    return get_conn().execute(
        """SELECT s.* FROM summaries s
           WHERE s.user_id = %s AND s.account_id = %s AND s.thread_id = %s
             AND (%s::text IS NULL OR s.model = %s)
             AND NOT EXISTS (
                 SELECT 1 FROM emails e
                 WHERE e.user_id = s.user_id AND e.account_id = s.account_id
                   AND e.thread_id = s.thread_id AND e.created_at > s.created_at
             )
           ORDER BY s.created_at DESC LIMIT 1""",
        (user_id, account_id, thread_id, model, model),
    ).fetchone()


def save_draft(
    user_id: str, account_id: str, thread_id: str, tone: str, length: str, content: str
) -> Row:
    return get_conn().execute(
        """INSERT INTO drafts (user_id, account_id, thread_id, tone, length, content)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (user_id, account_id, thread_id, tone, length, content),
    ).fetchone()


def save_action_items(
    user_id: str, account_id: str, thread_id: str, items: list[dict[str, Any]]
) -> list[Row]:
    conn = get_conn()
    out = []
    for item in items:
        due = item.get("due_date")
        due_date = date.fromisoformat(due) if due else None
        row = conn.execute(
            """INSERT INTO action_items (user_id, account_id, thread_id, description, owner, due_date)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING RETURNING *""",
            (user_id, account_id, thread_id, item["description"], item.get("owner"),
             due_date),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """SELECT * FROM action_items
                   WHERE user_id = %s AND account_id = %s AND thread_id = %s
                     AND lower(description) = lower(%s)
                     AND owner IS NOT DISTINCT FROM %s
                     AND due_date IS NOT DISTINCT FROM %s""",
                (user_id, account_id, thread_id, item["description"], item.get("owner"), due_date),
            ).fetchone()
        out.append(row)
    return out


def list_action_items(user_id: str, status: str | None = None) -> list[Row]:
    return get_conn().execute(
        """SELECT * FROM action_items WHERE user_id = %s AND (%s::text IS NULL OR status = %s)
           ORDER BY due_date NULLS LAST, created_at DESC""",
        (user_id, status, status),
    ).fetchall()


def set_action_item_status(user_id: str, item_id: str, status: str) -> Row | None:
    return get_conn().execute(
        "UPDATE action_items SET status = %s WHERE id = %s AND user_id = %s RETURNING *",
        (status, item_id, user_id),
    ).fetchone()
