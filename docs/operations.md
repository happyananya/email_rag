# Operations runbook

This runbook covers deployment, rollback, and failed-ingestion recovery for the shared `dev`
environment. Announce a deployment in the team channel first; only one person should deploy or
redrive messages at a time.

## Pre-deployment checks

```bash
export AWS_PROFILE=email-rag
aws sts get-caller-identity
make test
make lint
make frontend-build
make synth
git diff --check
```

Review the proposed infrastructure change before applying it:

```bash
cd infra
npx -y aws-cdk@latest diff --all -c stage=dev
cd ..
```

Do not deploy while a backfill or DLQ redrive is running. The Gmail retry fix deliberately limits
the ingestion worker to two concurrent Lambda instances to protect the Gmail per-user quota.

## Deploy

```bash
make deploy STAGE=dev
make outputs STAGE=dev
```

CloudFormation applies database migrations through the migration trigger. After deployment:

1. Confirm all four `EmailRag-dev-*` stacks show `UPDATE_COMPLETE`.
2. Check the `EmailRag-dev-Backend-Ops` CloudWatch dashboard and alarms.
3. Sign in to the application and smoke-test Inbox, Summary, Draft, Action items, and Ask.
4. Confirm the ingestion queue age returns to zero and no new messages enter the DLQ.

## Roll back

CloudFormation automatically rolls back a failed stack update. For an application regression after
a successful deployment, redeploy the last known-good Git commit; do not edit AWS resources by hand.

```bash
git log --oneline -10
git switch --detach <known-good-commit>
make deploy STAGE=dev
git switch -
```

Migrations are forward-only. Never delete a row from `schema_migrations` or manually reverse a
production schema change. If a schema migration must be corrected, add a new numbered migration
that is backward-compatible with the previously deployed application, then deploy it normally.

If the latest change is only frontend code, the same known-good deployment restores the S3 web
artifact and CloudFront distribution configuration.

## Inspect the ingestion DLQ

```bash
make dlq-status STAGE=dev
make dlq-peek STAGE=dev
```

`dlq-peek` does not delete messages and uses a zero-second visibility timeout. Inspect message bodies
and the Worker Lambda logs to find the repeated exception. Never paste raw email content or OAuth
tokens into tickets or chat.

Before redriving, all of these must be true:

- the code or configuration causing the failures has been fixed and deployed;
- a newly ingested test email completes successfully;
- the main queue has no old backlog;
- no Gmail backfill is running;
- the worker error alarm is healthy.

## Redrive the DLQ

The command is guarded to prevent accidental bulk replay:

```bash
make dlq-redrive STAGE=dev CONFIRM=redrive
```

Monitor the main queue depth, oldest-message age, Worker Lambda errors, Gmail throttling, and DLQ.
The SQS move task returns failed messages to their original source queue. Do not purge the DLQ:
purging is irreversible and removes the evidence needed to diagnose any remaining failures.

If errors resume, cancel the active move task from the SQS console or with
`aws sqs cancel-message-move-task --task-handle <handle>`, preserve the remaining DLQ messages, and
fix the new root cause before trying again.

## Enable GitHub Actions deployment

The `deploy-dev` CI job is disabled until the repository variable `AWS_DEPLOY_ROLE_ARN` is set. The
role must trust only this repository's `main` branch through GitHub's OIDC provider and must be able
to assume the CDK bootstrap roles. Configure these GitHub environment variables for `dev`:

- `AWS_DEPLOY_ROLE_ARN`
- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_USER_POOL_ID`
- `NEXT_PUBLIC_USER_POOL_CLIENT_ID`

Protect the `dev` GitHub environment with a required reviewer if the team wants a manual approval
between green CI and deployment.
