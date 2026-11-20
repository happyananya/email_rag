.PHONY: setup backend-setup infra-setup frontend-setup db-up migrate test lint frontend-dev frontend-build synth deploy outputs

PY ?= python3.12
CDK ?= npx -y aws-cdk@latest
STAGE ?= dev

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
	cd backend && DATABASE_URL=$${DATABASE_URL:-postgresql://emailrag:emailrag@localhost:5432/emailrag} \
		.venv/bin/python -m email_rag.handlers.migrate

test:
	cd backend && .venv/bin/pytest -q

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
	cd infra && $(CDK) deploy --all -c stage=$(STAGE) --require-approval broadening

outputs:
	aws cloudformation describe-stacks --query "Stacks[?starts_with(StackName, 'EmailRag-$(STAGE)')].Outputs[]" --output table
