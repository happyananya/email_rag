# Architecture → code map

Source documents: [project-proposal.pdf](project-proposal.pdf), [architecture.pdf](architecture.pdf).
Step numbers refer to the arrows on the architecture diagram.

## 1. Frontend & Authentication (1–7)

| Component | Where |
|---|---|
| Route 53 + ACM (optional custom domain) | `infra/stacks/frontend.py` (`-c domainName=... -c hostedZoneName=...`) |
| S3 web bucket + CloudFront (OAC, HTTPS) | `infra/stacks/frontend.py` |
| Next.js SPA (static export) | `frontend/` |
| Cognito user pool + web client | `infra/stacks/auth.py`; SPA uses Amplify `Authenticator` (`frontend/src/app/providers.tsx`) |
| Cognito authorizer on API Gateway | `infra/stacks/backend.py` (`CognitoUserPoolsAuthorizer`) |

## 2. API & Orchestration (7–11)

- **API Gateway → API Lambda** (`backend/src/email_rag/handlers/api.py`): accounts, threads,
  summaries, drafts, action items, `/ask`.
- **Connect Gmail**: SPA calls `POST /accounts/gmail/connect` → redirects to Google →
  Google returns to `/auth/callback` → SPA posts the code to `POST /accounts/gmail/callback`
  → tokens stored in **Secrets Manager** (`email-rag/oauth/{user_id}/{email}`) → **Step Functions**
  backfill started.
- **Backfill state machine** (`infra/stacks/backend.py`, tasks in `handlers/backfill.py`):
  `Start` (records current `historyId`) → `ListPage` loop (enqueue ids, capped by
  `MAX_BACKFILL_MESSAGES`) → `Finish` (Gmail `watch`, status `active`).

## 3. Email Ingestion Pipeline (12–24)

- **EventBridge rule** (every 15 min) and **Gmail push** (Pub/Sub → `POST /webhooks/gmail?token=`)
  both invoke the **Sync Lambda** (`handlers/sync.py`), which calls the History API and puts new
  message ids on **SQS**.
- **Worker Lambda** (`handlers/worker.py` → `services/ingest.py`): fetch raw message → S3 →
  parse MIME (`services/mime.py`) → chunk (`services/chunking.py`) → embed
  (`services/embeddings.py`) → insert into `email_chunks`.
- Partial batch failures are retried; after 4 receives a message goes to the **DLQ** (alarmed).

## 4. AI & Data Storage (25–28)

- **Amazon Bedrock**
  - Embeddings: Titan Text Embeddings V2 (`amazon.titan-embed-text-v2:0`, 1024 dims).
  - LLM: Claude via the Anthropic SDK's `AnthropicBedrockMantle` client
    (`services/llm.py`, default `anthropic.claude-opus-5-5`, `LLM_EFFORT=low` for latency).
    Action items use structured JSON output. Email text is wrapped in `<email>` tags and the system
    prompt treats it as untrusted (prompt-injection guard).
- **Aurora PostgreSQL Serverless v2 + pgvector** (`infra/stacks/data.py`, schema in
  `backend/src/email_rag/migrations/`). HNSW cosine index on `email_chunks.embedding`.
- **RAG** (`services/rag.py`): embed question → top-k chunks filtered by `user_id` (and optionally
  `account_id`) → Claude answers with `[n]` citations → API returns cited source emails.
- **S3 email bucket**: raw MIME at `users/{user_id}/accounts/{account_id}/messages/{id}.eml`.

## 5. Security & Monitoring

- Secrets Manager: Google OAuth client, per-account OAuth tokens, webhook token, DB credentials.
- KMS customer-managed key (rotation on) encrypts Aurora and the email bucket.
- Tenant isolation: every repository query in `backend/src/email_rag/repo.py` filters by `user_id`;
  S3 keys are prefixed by `user_id`.
- Disconnecting an account deletes its token secret, its S3 prefix and all DB rows (FK cascade).
- CloudWatch: alarms on DLQ depth, queue age, API 5xx and Lambda errors → SNS (email via
  `-c alarmEmail=...`); AWS Budget at 80% of `budgetUsd`; X-Ray tracing on Lambdas, API, Step Functions.

## Open items / next steps

- **Per-tenant encryption**: today one CMK encrypts all tenants' data. The proposal calls for
  per-tenant keys; options are a KMS key per user (cost: $1/key/month) or envelope encryption with
  a per-tenant data key and KMS encryption context.
- **Postgres row-level security** as defense in depth on top of the `user_id` filters.
- **Webhook auth**: switch from the shared `?token=` to verifying Pub/Sub's OIDC JWT.
- **Bedrock IAM**: tighten `bedrock:*` / `bedrock-mantle:*` resources to specific model ARNs and
  confirm the Mantle action names for your region.
- **Re-backfill** accounts whose History API cursor expired (sync marks them `status = 'error'`).
- Stretch goals from the proposal: Outlook/Yahoo, send via provider API, digests via SES,
  priority inbox, PII redaction with Comprehend.
