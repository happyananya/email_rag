"""Aurora PostgreSQL connection, reused across warm Lambda invocations."""

import json

import boto3
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from email_rag.config import settings

_conn: psycopg.Connection | None = None


def _dsn() -> str:
    s = settings()
    if s.database_url:
        return s.database_url
    if not s.db_secret_arn:
        raise RuntimeError("Set DATABASE_URL or DB_SECRET_ARN")
    secret = json.loads(
        boto3.client("secretsmanager").get_secret_value(SecretId=s.db_secret_arn)["SecretString"]
    )
    return (
        f"postgresql://{secret['username']}:{secret['password']}@{secret['host']}:"
        f"{secret['port']}/{secret.get('dbname', 'emailrag')}?sslmode=require"
    )


def get_conn() -> psycopg.Connection:
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(_dsn(), autocommit=True, row_factory=dict_row)
        register_vector(_conn)
    return _conn
