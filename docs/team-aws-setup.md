# Team AWS Setup & Division of Work

How the four of us share one AWS account, which IAM user each person gets, and who owns setting
up each AWS service in the architecture.

> **Golden rule: every AWS resource is created by CDK (`infra/`), not by clicking in the console.**
> The console is for *looking* (logs, metrics, test invocations). If you need a resource changed,
> edit the stack file you own, open a PR, and deploy. Console-made changes drift and get
> overwritten on the next deploy.

---

## 1. Roles and owners

| Role | Owner | Backup | Owns (AWS services) |
|---|---|---|---|
| **A. Infra & DevOps lead** | _(assign)_ | B | IAM, VPC/NAT, CloudFormation/CDK, CloudWatch, X-Ray, CloudTrail, Budgets, CI/CD |
| **B. Data & Ingestion** | _(assign)_ | C | RDS PostgreSQL + pgvector, S3 (email bucket), SQS + DLQ, Lambda (Sync, Worker, Backfill), Step Functions, EventBridge |
| **C. AI & API** | _(assign)_ | B | Amazon Bedrock, API Gateway, Lambda (API) |
| **D. Frontend, Auth & Security** | _(assign)_ | A | Route 53, ACM, S3 (web) + CloudFront, Cognito, Secrets Manager, KMS |

Team: Gurleen Kaur, Aman Kumar, Harindham Sharma, Ananya Agarwal. Fill in the Owner and Backup
columns above. The backup reviews the owner's PRs and can take over if the owner is blocked.

---

## 2. AWS account & IAM setup (Role A, day 1)

### 2.1 Root account hardening (done once by the account owner)

- [ ] Enable **MFA on the root user**; store root credentials somewhere only the account owner can reach.
- [ ] Never use root again after creating the IAM users below.
- [ ] Choose the region: **`us-east-1`** (required for CloudFront ACM certificates; widest Bedrock model availability).
- [ ] Billing → enable *IAM user and role access to billing information* so Role A can see costs.
- [ ] Create an **AWS Budget** right away (e.g. $50/month, alerts at 50% / 80% / 100% to all four emails).
  The CDK stack also creates one, but have one in place before anything is deployed.
- [ ] Enable a **CloudTrail** trail (management events, all regions) so every change is auditable.

### 2.2 IAM groups

| Group | Members | Policies | Why |
|---|---|---|---|
| `EmailRagAdmins` | A (+ one backup) | `AdministratorAccess` | CDK bootstrap, IAM changes, emergencies |
| `EmailRagDevelopers` | all 4 | `ReadOnlyAccess`, `EmailRagCdkDeploy`, `EmailRagSelfManage` | See everything, deploy via CDK roles, manage own password/MFA/keys |
| `EmailRagData` | B | `EmailRagDataOps` | Redrive DLQ, start/stop backfills, invoke Lambdas, query DB |
| `EmailRagAI` | C | `AmazonBedrockFullAccess`, `EmailRagApiOps` | Bedrock console playground, model access, API Gateway testing |
| `EmailRagSecurity` | D | `EmailRagSecurityOps` | Put secret values, manage Cognito users, invalidate CloudFront |

> `ReadOnlyAccess` lets everyone read CloudWatch logs, metrics, alarms and configurations, but **not**
> secret values or S3 object contents. Those come from the role groups.
> No developer group can read users' Gmail tokens (`email-rag/oauth/*`); only the Lambdas can.

### 2.3 IAM users

One IAM user per person (no shared logins). Suggested names: `gurleen`, `aman`, `harindham`, `ananya`.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Groups
for g in EmailRagAdmins EmailRagDevelopers EmailRagData EmailRagAI EmailRagSecurity; do
  aws iam create-group --group-name "$g"
done
aws iam attach-group-policy --group-name EmailRagAdmins     --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam attach-group-policy --group-name EmailRagDevelopers --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess
aws iam attach-group-policy --group-name EmailRagAI         --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess

# Users (repeat per person). --password-reset-required forces a new password at first login.
U=ananya
aws iam create-user --user-name "$U"
aws iam create-login-profile --user-name "$U" --password '<temporary-password>' --password-reset-required
aws iam add-user-to-group --user-name "$U" --group-name EmailRagDevelopers
aws iam add-user-to-group --user-name "$U" --group-name <EmailRagData|EmailRagAI|EmailRagSecurity|EmailRagAdmins>
```

Console sign-in URL for the team: `https://<ACCOUNT_ID>.signin.aws.amazon.com/console`

### 2.4 Custom policies

Create each with:
`aws iam create-policy --policy-name <Name> --policy-document file://<name>.json`, then
`aws iam attach-group-policy --group-name <Group> --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/<Name>`.
Replace `<ACCOUNT_ID>` in the JSON. Resource names start with `EmailRag-` (CloudFormation stack prefix)
or `email-rag/` (secrets), which keeps these scoped to our project.

**`EmailRagSelfManage`** (group `EmailRagDevelopers`): manage your own credentials; console sessions without MFA are denied.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageOwnCredentials",
      "Effect": "Allow",
      "Action": [
        "iam:ChangePassword", "iam:GetUser", "iam:GetLoginProfile",
        "iam:CreateAccessKey", "iam:DeleteAccessKey", "iam:ListAccessKeys", "iam:UpdateAccessKey",
        "iam:CreateVirtualMFADevice", "iam:EnableMFADevice", "iam:ListMFADevices",
        "iam:ResyncMFADevice", "iam:DeactivateMFADevice"
      ],
      "Resource": ["arn:aws:iam::*:user/${aws:username}", "arn:aws:iam::*:mfa/*"]
    },
    {
      "Sid": "DenyConsoleWithoutMfa",
      "Effect": "Deny",
      "NotAction": [
        "iam:ChangePassword", "iam:GetUser", "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice", "iam:ListMFADevices", "iam:ResyncMFADevice", "sts:GetSessionToken"
      ],
      "Resource": "*",
      "Condition": { "Bool": { "aws:MultiFactorAuthPresent": "false" } }
    }
  ]
}
```

> This uses `Bool` (not `BoolIfExists`) on purpose: console sessions must use MFA, while CLI calls
> made with access keys (which carry no MFA flag) still work for `cdk deploy`.

**`EmailRagCdkDeploy`** (group `EmailRagDevelopers`): deploy through the CDK bootstrap roles instead of holding broad permissions directly.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/cdk-*"
    }
  ]
}
```

**`EmailRagDataOps`** (group `EmailRagData`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "QueuesAndDlqRedrive",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:PurgeQueue", "sqs:SendMessage",
        "sqs:StartMessageMoveTask", "sqs:ListMessageMoveTasks", "sqs:CancelMessageMoveTask"
      ],
      "Resource": "arn:aws:sqs:us-east-1:<ACCOUNT_ID>:EmailRag-*"
    },
    {
      "Sid": "InvokePipelineLambdas",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:EmailRag-*"
    },
    {
      "Sid": "Backfills",
      "Effect": "Allow",
      "Action": ["states:StartExecution", "states:StopExecution", "states:RedriveExecution"],
      "Resource": [
        "arn:aws:states:us-east-1:<ACCOUNT_ID>:stateMachine:Backfill*",
        "arn:aws:states:us-east-1:<ACCOUNT_ID>:execution:Backfill*:*"
      ]
    },
    {
      "Sid": "RawEmailDebugging",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::emailrag-*-data-emailbucket*/*"
    },
    {
      "Sid": "DbQueryEditor",
      "Effect": "Allow",
      "Action": ["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement",
                 "rds-data:BeginTransaction", "rds-data:CommitTransaction", "rds-data:RollbackTransaction"],
      "Resource": "arn:aws:rds:us-east-1:<ACCOUNT_ID>:cluster:*"
    },
    {
      "Sid": "DbSecretForQueryEditor",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:<ACCOUNT_ID>:secret:email-rag/db*"
    }
  ]
}
```

**`EmailRagApiOps`** (group `EmailRagAI`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TestApiAndLambda",
      "Effect": "Allow",
      "Action": ["apigateway:POST", "lambda:InvokeFunction"],
      "Resource": [
        "arn:aws:apigateway:us-east-1::/restapis/*",
        "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:EmailRag-*"
      ]
    }
  ]
}
```

**`EmailRagSecurityOps`** (group `EmailRagSecurity`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AppSecrets",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue",
                 "secretsmanager:DescribeSecret"],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:<ACCOUNT_ID>:secret:email-rag/google-oauth-client*",
        "arn:aws:secretsmanager:us-east-1:<ACCOUNT_ID>:secret:email-rag/gmail-webhook*"
      ]
    },
    {
      "Sid": "CognitoUserAdmin",
      "Effect": "Allow",
      "Action": ["cognito-idp:Admin*", "cognito-idp:ListUsers", "cognito-idp:DescribeUserPool"],
      "Resource": "arn:aws:cognito-idp:us-east-1:<ACCOUNT_ID>:userpool/*"
    },
    {
      "Sid": "CdnInvalidation",
      "Effect": "Allow",
      "Action": ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
      "Resource": "*"
    }
  ]
}
```

> Generated resource names (bucket, queues, functions) follow the patterns above; confirm the real
> names with `make outputs` after the first deploy and adjust the ARNs if needed.
>
> The database sits in isolated subnets with no public endpoint. Inspect it through a controlled
> VPC connection (for example, an SSM tunnel) rather than exposing it publicly.

### 2.5 Each person, on first login

- [ ] Sign in at the console URL, set a new password, **register an MFA device** (IAM → Security credentials).
- [ ] Create **one access key** for the CLI; never commit it, never paste it in Slack/Discord.
- [ ] Configure a named profile and use it everywhere:
  ```bash
  aws configure --profile email-rag      # region us-east-1, output json
  export AWS_PROFILE=email-rag
  aws sts get-caller-identity            # should show your IAM user
  ```
- [ ] Rotate your access key if it is ever exposed: `aws iam create-access-key` then delete the old one.

---

## 3. Service ownership matrix

Every AWS service in the architecture, who sets it up, and where it lives in code.

| # | AWS service | Owner | Defined in | Setup / configuration tasks |
|---|---|---|---|---|
| 1 | IAM (users, groups, policies) | A | console/CLI (section 2) | Groups, users, MFA, custom policies |
| 2 | CloudFormation / CDK bootstrap | A | `infra/app.py` | `cdk bootstrap`, first `cdk deploy --all` |
| 3 | VPC, subnets, NAT gateway, S3 endpoint | A | `infra/stacks/data.py` | Review CIDRs, NAT cost, add VPC endpoints if needed |
| 4 | CloudWatch (logs, alarms, dashboard) | A | `infra/stacks/backend.py` | Alarm email, build dashboard |
| 5 | X-Ray | A | Lambda/API/SFN `tracing` flags | Verify traces end-to-end |
| 6 | AWS Budgets | A | `infra/stacks/backend.py` + console | Budget amount, alert emails |
| 7 | CloudTrail | A | console | Org trail, all regions |
| 8 | RDS PostgreSQL 16 + pgvector | B | `infra/stacks/data.py`, `backend/src/email_rag/migrations/` | Instance sizing, migrations, index tuning |
| 9 | S3: raw email bucket | B | `infra/stacks/data.py` | Lifecycle rules, prefix layout |
| 10 | SQS ingestion queue + DLQ | B | `infra/stacks/backend.py` | Visibility timeout, max receives, redrive |
| 11 | Lambda: Sync, Worker, Backfill, Migrate | B | `infra/stacks/backend.py`, `backend/.../handlers/` | Memory/timeout/concurrency tuning |
| 12 | Step Functions (backfill) | B | `infra/stacks/backend.py` | Retry/catch states, error handling |
| 13 | EventBridge (sync schedule) | B | `infra/stacks/backend.py` | Schedule rate |
| 14 | Amazon Bedrock (Claude + Titan embeddings) | C | `backend/.../services/llm.py`, `embeddings.py` | Model access, model choice, IAM, latency |
| 15 | API Gateway (REST + Cognito authorizer) | C | `infra/stacks/backend.py` | Throttling, CORS, stage, usage metrics |
| 16 | Lambda: API | C | `backend/.../handlers/api.py` | Memory/timeout, provisioned concurrency for cold starts |
| 17 | Route 53 (custom domain) | D | `infra/stacks/frontend.py` | Hosted zone, records |
| 18 | ACM (TLS certificate) | D | `infra/stacks/frontend.py` | DNS validation |
| 19 | S3 (web bucket) + CloudFront | D | `infra/stacks/frontend.py` | OAC, caching, error pages, security headers |
| 20 | Cognito user pool | D | `infra/stacks/auth.py` | Password policy, email verification, MFA option |
| 21 | Secrets Manager | D | `infra/stacks/data.py` | Google OAuth client, webhook token, rotation |
| 22 | KMS | D | `infra/stacks/data.py` | Key policy, per-tenant encryption design |

Outside AWS: **Google Cloud** (Gmail API, OAuth consent screen, Pub/Sub push) is split: D owns the
OAuth client and consent screen, and B owns the Pub/Sub topic and push subscription.

---

## 4. Task lists per role

### A. Infra & DevOps lead

- [ ] A1. Root hardening, budget, CloudTrail, IAM groups/users/policies (section 2).
- [x] A2. `npx aws-cdk@latest bootstrap aws://<ACCOUNT_ID>/us-east-1`.
- [x] A3. First `make deploy STAGE=dev`; share `make outputs` with the team (pin them in the team chat).
- [ ] A4. Set `alarmEmail` and `budgetUsd` in `infra/cdk.json`; confirm the SNS subscription email.
- [x] A5. CloudWatch dashboard: API latency p50/p90, Lambda errors/duration, queue depth/age, DLQ, Bedrock latency.
- [ ] A6. CI/CD: GitHub OIDC identity provider + `GitHubDeployRole` (assumes `cdk-*` roles); add a deploy job on `main` to `.github/workflows/ci.yml`.
- [ ] A7. Cost review each week (Cost Explorer by service); NAT and RDS are the biggest fixed costs.
- [x] A8. Write the "how to deploy" and "how to roll back" runbook in `docs/operations.md`.

### B. Data & Ingestion

- [x] B1. Run `make db-up && make migrate` locally; fix any SQL issues before the first AWS deploy.
- [ ] B2. Verify the private RDS PostgreSQL connection and migration Lambda after deployment.
- [ ] B3. Review `db.t4g.micro` CPU/storage metrics and resize only if the test workload requires it.
- [x] B4. Verify the backfill state machine and its terminal `Catch` on a test Gmail account.
- [ ] B5. Verify that an expired Gmail History API cursor automatically starts a fresh backfill.
- [ ] B6. Gmail push: Google Cloud Pub/Sub topic, grant `gmail-api-push@system.gserviceaccount.com`
      Publisher, push subscription to the `GmailWebhookPath` output, deploy with `-c gmailPubsubTopic=...`.
- [x] B7. DLQ runbook: how to inspect and redrive failed messages.
- [x] B8. S3 lifecycle rule for the email bucket (Intelligent-Tiering after 30 days).
- [x] B9. Integration tests for `services/ingest.py` with a sample `.eml` corpus.

### C. AI & API

- [x] C1. **Day 1:** Bedrock console → *Model access* → request Claude and Titan Text Embeddings V2 (approval can take time).
- [x] C2. Confirm the Claude model ID available in `us-east-1`; set `llmModelId` context if it differs.
- [x] C3. After the first successful Lambda invocation, tighten Bedrock `resources` from `*` to the
      final foundation-model and inference-profile ARNs.
- [ ] C4. Measure latency: summary < ~10 s, draft < ~15 s. Tune `max_tokens` or evaluate another model if needed.
- [ ] C5. Build a small RAG eval set (20–30 questions with known answers from a test inbox); tune chunk size and `RAG_TOP_K`.
- [x] C6. API Gateway: throttling per stage, access logging, request validation.
- [x] C7. Summary caching: return the stored summary unless the thread has new messages.
- [ ] C8. API integration tests (local Postgres + mocked Bedrock).

### D. Frontend, Auth & Security

- [x] D1. Google Cloud: create the project, enable the Gmail API, set up the OAuth consent screen (add all 4 as **test users**), and create a Web OAuth client with redirect URIs `<WebUrl>/auth/callback` and `http://localhost:3000/auth/callback`.
- [x] D2. Put the Google client credentials into `email-rag/google-oauth-client` (Secrets Manager).
- [x] D3. Fill `frontend/.env.local` from the outputs; redeploy so the SPA is built with them.
- [ ] D4. Cognito: confirm email verification works; decide on optional MFA for app users.
- [ ] D5. Verify the CloudFront security response-headers policy and static-route rewrites after deploy.
- [ ] D6. Optional custom domain: Route 53 hosted zone + `-c domainName=... -c hostedZoneName=...`.
- [ ] D7. **Per-tenant encryption** (promised in the proposal): design and implement either a KMS key per user or envelope encryption with a per-tenant data key + encryption context.
- [ ] D8. Postgres **row-level security** policies (with B) as a second safeguard on top of the `user_id` filters.
- [ ] D9. Replace the webhook `?token=` check with verification of Pub/Sub's signed OIDC token (with B).
- [x] D10. UI polish: loading states, inline errors/status, empty states, mobile layout.

---

## 5. Setup order

```
Day 1   A: account hardening, IAM users ──┐       C: request Bedrock model access
        D: Google Cloud project + OAuth   │
        B: local DB + migrations          │
Day 2   A: cdk bootstrap + first deploy ◄─┘
        D: store Google secret, frontend env, redeploy
Day 3   Everyone: end-to-end smoke test on a test Gmail account
        (sign up → connect Gmail → backfill → summarize / draft / action items / ask)
Week 2+ Role task lists in parallel; weekly cost review (A); demo dry-run before the deadline
```

Blocking dependencies: C1 (Bedrock access) and D1/D2 (Google OAuth) gate the smoke test; A3 gates everything on AWS.

---

## 6. Shared rules

- **One shared `dev` stage.** Personal stacks (`-c stage=<name>`) each create their own NAT gateway and
  RDS instance, which multiplies fixed cost. Only use them briefly and destroy them afterwards
  (`npx aws-cdk@latest destroy --all -c stage=<name>`).
- **Coordinate deploys** in the team chat ("deploying Backend to dev") since we share one stage.
- **PRs need the backup's review** for changes to stacks in `infra/`.
- **No secrets in git**, ever. `.env*` files are gitignored; credentials live in Secrets Manager.
- **Tag everything** via CDK (already tags `project=email-rag`, `stage=<stage>`) so Cost Explorer can filter.
- **Use test Gmail accounts** for development, not personal inboxes.

### Rough fixed monthly cost (dev, us-east-1, idle)

| Item | Approx. | Note |
|---|---|---|
| NAT gateway | ~$33 + data | Biggest fixed cost; VPC endpoints can reduce data charges |
| RDS PostgreSQL `db.t4g.micro` | Free-plan eligible / usage-based | Single-AZ, 20 GiB gp3 |
| Secrets Manager | ~$0.40 per secret | One per connected Gmail account + app secrets |
| KMS key | ~$1 | Per key; per-tenant keys add $1/user |
| Lambda, SQS, API GW, S3, CloudFront | low | Usage-based; small for a class project |
| Bedrock | usage-based | Watch embedding volume during backfills |

Check the current AWS pricing pages for exact numbers; these are planning estimates.
