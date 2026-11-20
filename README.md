# Email RAG SaaS Platform

A cloud-native, multi-tenant SaaS that connects to Gmail via OAuth 2.0, **summarizes threads**,
**drafts replies**, **extracts action items**, and answers **natural-language questions over the
whole inbox** with Retrieval-Augmented Generation on AWS.

Team: Gurleen Kaur, Aman Kumar, Harindham Sharma, Ananya Agarwal.
See [docs/project-proposal.pdf](docs/project-proposal.pdf), [docs/architecture.pdf](docs/architecture.pdf)
and the code map in [docs/architecture.md](docs/architecture.md).

## Architecture at a glance

```
Browser ─ Route 53 ─ CloudFront ─ S3 (Next.js SPA)          Cognito (JWT)
   │
   └─ API Gateway (Cognito authorizer) ─ API Lambda ─┬─ Bedrock (Claude + Titan embeddings)
                                                     ├─ Aurora PostgreSQL + pgvector
                                                     ├─ S3 (raw emails)
                                                     └─ Step Functions (initial backfill)
EventBridge (15 min) ┐                                          │
Gmail push → Pub/Sub ┴─ Sync Lambda (History API) ─ SQS ─ Worker Lambda ─ S3 / Bedrock / Aurora
                                                     └─ DLQ
Secrets Manager (OAuth tokens) · KMS · CloudWatch alarms · AWS Budgets
```

## Repository layout

```
backend/            Python 3.12 Lambdas
  src/email_rag/
    handlers/       api.py, sync.py, worker.py, backfill.py, migrate.py (Lambda entry points)
    services/       gmail, mime, chunking, embeddings, llm, rag, ingest, queue, storage, secrets
    migrations/     SQL schema (pgvector)
    repo.py         data access (every query tenant-filtered)
  tests/
frontend/           Next.js (static export) + Amplify Auth: inbox, ask, action items, accounts
infra/              AWS CDK (Python): Frontend, Auth, Data, Backend stacks
docs/               proposal, architecture, code map
docker-compose.yml  local Postgres + pgvector
```

## Prerequisites

- Python 3.12, Node 22+, AWS CLI v2 with credentials, Docker (local DB only)
- Bedrock model access enabled in your region for **Claude** and **Titan Text Embeddings V2**
- A Google Cloud project with the Gmail API enabled and an OAuth client (Web application)

## Local development

```bash
make setup          # venvs + npm install
make db-up          # Postgres + pgvector in Docker
make migrate        # apply schema
make test           # backend unit tests
make lint
```

Frontend against a deployed backend:

```bash
cp frontend/.env.example frontend/.env.local   # fill from `make outputs`
make frontend-dev                               # http://localhost:3000
```

## Deploying to AWS

```bash
npx aws-cdk@latest bootstrap        # once per account/region
make deploy STAGE=dev               # builds the SPA and deploys all stacks
make outputs                        # API URL, Cognito ids, web URL, ...
```

Useful context flags (`infra/cdk.json` or `-c key=value`): `alarmEmail`, `budgetUsd`,
`domainName` + `hostedZoneName` (custom domain; deploy in us-east-1), `gmailPubsubTopic`,
`llmModelId`.

After the first deploy:

1. **Google OAuth client** – add `<WebUrl>/auth/callback` (and `http://localhost:3000/auth/callback`)
   as an authorized redirect URI, then store the credentials:
   ```bash
   aws secretsmanager put-secret-value --secret-id email-rag/google-oauth-client \
     --secret-string '{"client_id":"...","client_secret":"..."}'
   ```
   While the app is unverified, add team members as **test users** on the OAuth consent screen.
2. **Frontend config** – put `ApiUrl`, `UserPoolId`, `UserPoolClientId` into `frontend/.env.local`
   and run `make deploy` again so the SPA is rebuilt with them.
3. **Gmail push (optional, scheduled sync works without it)** – create a Pub/Sub topic, grant
   `gmail-api-push@system.gserviceaccount.com` the Publisher role, create a push subscription to
   the `GmailWebhookPath` output with the token from secret `email-rag/gmail-webhook`, then redeploy
   with `-c gmailPubsubTopic=projects/<project>/topics/<topic>`.

## Conventions

- Every tenant-owned table has `user_id`; every query in `repo.py` filters by it. Keep it that way.
- Raw email lives in S3 under `users/{user_id}/...`; Postgres stores metadata, chunks and vectors.
- Email content sent to the LLM is untrusted: keep it inside `<email>` tags (see `services/llm.py`).
- Schema changes: add a new numbered file in `backend/src/email_rag/migrations/`; it runs on deploy.
