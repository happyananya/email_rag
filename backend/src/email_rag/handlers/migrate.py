"""Applies SQL migrations in email_rag/migrations in order. Run by a CDK Trigger on each deploy,
or locally with `python -m email_rag.handlers.migrate` (uses DATABASE_URL)."""

from importlib import resources

import psycopg

from email_rag.db import _dsn


def run() -> list[str]:
    applied = []
    # Plain connection: pgvector types may not exist yet, so don't register them here.
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        files = sorted(
            f for f in resources.files("email_rag.migrations").iterdir() if f.name.endswith(".sql")
        )
        for f in files:
            if f.name in done:
                continue
            with conn.transaction():
                conn.execute(f.read_text())
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    return applied


def handler(event, context):
    return {"applied": run()}


if __name__ == "__main__":
    print(run())
