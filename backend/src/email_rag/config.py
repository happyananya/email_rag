"""Runtime configuration, read from environment variables set by CDK (or .env locally)."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    aws_region: str
    # Database: DATABASE_URL for local dev, DB_SECRET_ARN (RDS-generated secret) in AWS.
    database_url: str | None
    db_secret_arn: str | None
    email_bucket: str
    ingest_queue_url: str
    backfill_state_machine_arn: str
    # Bedrock
    llm_model_id: str
    llm_effort: str
    embedding_model_id: str
    embedding_dimensions: int
    # Google OAuth / Gmail
    google_client_secret_arn: str
    oauth_redirect_uri: str
    gmail_pubsub_topic: str
    webhook_secret_arn: str
    frontend_url: str
    # RAG
    rag_top_k: int


@lru_cache
def settings() -> Settings:
    env = os.environ.get
    return Settings(
        aws_region=env("AWS_REGION", "us-east-1"),
        database_url=env("DATABASE_URL"),
        db_secret_arn=env("DB_SECRET_ARN"),
        email_bucket=env("EMAIL_BUCKET", "email-rag-local"),
        ingest_queue_url=env("INGEST_QUEUE_URL", ""),
        backfill_state_machine_arn=env("BACKFILL_STATE_MACHINE_ARN", ""),
        llm_model_id=env("LLM_MODEL_ID", "anthropic.claude-opus-5-5"),
        llm_effort=env("LLM_EFFORT", "low"),
        embedding_model_id=env("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
        embedding_dimensions=int(env("EMBEDDING_DIMENSIONS", "1024")),
        google_client_secret_arn=env("GOOGLE_CLIENT_SECRET_ARN", ""),
        oauth_redirect_uri=env("OAUTH_REDIRECT_URI", "http://localhost:3000/auth/callback"),
        gmail_pubsub_topic=env("GMAIL_PUBSUB_TOPIC", ""),
        webhook_secret_arn=env("WEBHOOK_SECRET_ARN", ""),
        frontend_url=env("FRONTEND_URL", "http://localhost:3000"),
        rag_top_k=int(env("RAG_TOP_K", "8")),
    )
