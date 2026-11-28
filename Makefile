.PHONY: setup backend-setup infra-setup frontend-setup db-up migrate test test-integration lint frontend-dev frontend-build synth deploy outputs dlq-status dlq-peek dlq-redrive

PY ?= python3.12
CDK ?= npx -y aws-cdk@latest
STAGE ?= dev
DEPLOY_APPROVAL ?= broadening

setup: backend-setup infra-setup frontend-setup

backend-setup:
	cd backend && $(PY) -m venv .venv && .venv/bin/pip install -q -e '.[dev]'

infra-setup:
	cd infra && $(PY) -m venv .venv && .venv/bin/pip install -q -r requirements.txt

frontend-setup:
	cd frontend && npm install

db-up:
	docker compose up -d --wait db

migrate:
	cd backend && DATABASE_URL=$${DATABASE_URL:-postgresql://emailrag:emailrag@localhost:5433/emailrag} \
		.venv/bin/python -m email_rag.handlers.migrate

test:
	cd backend && .venv/bin/pytest -q

test-integration: db-up migrate
	cd backend && TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql://emailrag:emailrag@localhost:5433/emailrag} \
		.venv/bin/pytest -q tests/integration

lint:
	cd backend && .venv/bin/ruff check src tests
	cd frontend && npm run lint

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

synth:
	cd infra && $(CDK) synth -c stage=$(STAGE)

# Builds the SPA first so the Frontend stack uploads it to S3.
deploy: frontend-build
	cd infra && $(CDK) deploy --all -c stage=$(STAGE) --require-approval $(DEPLOY_APPROVAL)

outputs:
	aws cloudformation describe-stacks --query "Stacks[?starts_with(StackName, 'EmailRag-$(STAGE)')].Outputs[]" --output table

dlq-status:
	@DLQ_URL=$$(aws cloudformation describe-stacks --stack-name EmailRag-$(STAGE)-Backend \
		--query "Stacks[0].Outputs[?OutputKey=='IngestDlqUrl'].OutputValue | [0]" --output text); \
	test "$$DLQ_URL" != "None" || { echo "IngestDlqUrl output not found; deploy the latest backend stack first."; exit 1; }; \
	aws sqs get-queue-attributes --queue-url "$$DLQ_URL" \
		--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
		ApproximateNumberOfMessagesDelayed RedrivePolicy

# Safe inspection: receives at most 10 messages with zero visibility timeout and never deletes them.
dlq-peek:
	@DLQ_URL=$$(aws cloudformation describe-stacks --stack-name EmailRag-$(STAGE)-Backend \
		--query "Stacks[0].Outputs[?OutputKey=='IngestDlqUrl'].OutputValue | [0]" --output text); \
	test "$$DLQ_URL" != "None" || { echo "IngestDlqUrl output not found; deploy the latest backend stack first."; exit 1; }; \
	aws sqs receive-message --queue-url "$$DLQ_URL" --max-number-of-messages 10 \
		--visibility-timeout 0 --wait-time-seconds 0 --attribute-names All \
		--message-attribute-names All --output json

# Intentionally guarded: only redrive after fixing the root cause and checking queue capacity.
dlq-redrive:
	@test "$(CONFIRM)" = "redrive" || { echo "Refusing. Re-run with CONFIRM=redrive after following docs/operations.md."; exit 1; }
	@DLQ_ARN=$$(aws cloudformation describe-stacks --stack-name EmailRag-$(STAGE)-Backend \
		--query "Stacks[0].Outputs[?OutputKey=='IngestDlqArn'].OutputValue | [0]" --output text); \
	test "$$DLQ_ARN" != "None" || { echo "IngestDlqArn output not found; deploy the latest backend stack first."; exit 1; }; \
	aws sqs start-message-move-task --source-arn "$$DLQ_ARN"
