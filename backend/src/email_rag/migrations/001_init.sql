-- Email RAG SaaS: initial schema (Aurora PostgreSQL 16 + pgvector)
-- Tenant isolation: every tenant-owned row carries user_id, and every query filters on it.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cognito_sub  text NOT NULL UNIQUE,
    email        text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_accounts (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider         text NOT NULL DEFAULT 'gmail',
    email_address    text NOT NULL,
    secret_arn       text NOT NULL,          -- OAuth tokens live in Secrets Manager
    history_id       text,                   -- Gmail History API cursor
    watch_expiration timestamptz,            -- Gmail users.watch expiry
    status           text NOT NULL DEFAULT 'backfilling', -- backfilling | active | error | disconnected
    last_synced_at   timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, email_address)
);
CREATE INDEX IF NOT EXISTS email_accounts_email_idx ON email_accounts (email_address);

CREATE TABLE IF NOT EXISTS emails (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id          uuid NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    provider_message_id text NOT NULL,
    thread_id           text NOT NULL,
    subject             text,
    sender              text,
    recipients          jsonb NOT NULL DEFAULT '[]',
    sent_at             timestamptz,
    snippet             text,
    labels              text[] NOT NULL DEFAULT '{}',
    s3_key              text NOT NULL,       -- raw MIME in S3 under users/{user_id}/...
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id, provider_message_id)
);
CREATE INDEX IF NOT EXISTS emails_user_account_sent_idx ON emails (user_id, account_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS emails_thread_idx ON emails (account_id, thread_id);

-- Dimension must match EMBEDDING_DIMENSIONS (Titan Text Embeddings V2 default: 1024).
CREATE TABLE IF NOT EXISTS email_chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id   uuid NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    email_id     uuid NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    chunk_index  int  NOT NULL,
    content      text NOT NULL,
    embedding    vector(1024) NOT NULL,
    UNIQUE (email_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS email_chunks_user_account_idx ON email_chunks (user_id, account_id);
CREATE INDEX IF NOT EXISTS email_chunks_embedding_hnsw
    ON email_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS summaries (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  uuid NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    thread_id   text NOT NULL,
    content     text NOT NULL,
    model       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS summaries_thread_idx ON summaries (user_id, account_id, thread_id);

CREATE TABLE IF NOT EXISTS drafts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  uuid NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    thread_id   text NOT NULL,
    tone        text NOT NULL,
    length      text NOT NULL,
    content     text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS action_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  uuid NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    thread_id   text NOT NULL,
    description text NOT NULL,
    owner       text,
    due_date    date,
    status      text NOT NULL DEFAULT 'open', -- open | done
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS action_items_user_idx ON action_items (user_id, status);
