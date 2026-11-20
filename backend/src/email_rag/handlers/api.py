"""API Lambda: REST backend behind API Gateway + Cognito authorizer (diagram steps 7-11, 25-28)."""

import json
from datetime import datetime

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, NotFoundError

from email_rag import repo
from email_rag.config import settings
from email_rag.services import gmail, llm, rag, secrets, storage
from email_rag.services.mime import parse_raw

logger = Logger()
tracer = Tracer()
app = APIGatewayRestResolver(cors=CORSConfig(allow_origin=settings().frontend_url))


# --- helpers ---------------------------------------------------------------

def current_user() -> dict:
    """Cognito authorizer has already validated the JWT; map its sub to our users row."""
    claims = app.current_event.request_context.authorizer.claims or {}
    return repo.upsert_user(claims["sub"], claims.get("email", ""))


def require_account(user_id: str, account_id: str) -> dict:
    account = repo.get_account(user_id, account_id)
    if not account:
        raise NotFoundError("account not found")
    return account


def load_thread(user_id: str, account_id: str, thread_id: str) -> list[dict]:
    rows = repo.get_thread_emails(user_id, account_id, thread_id)
    if not rows:
        raise NotFoundError("thread not found")
    out = []
    for r in rows:
        parsed = parse_raw(storage.get_raw_email(r["s3_key"]))
        out.append({
            "id": str(r["id"]),
            "subject": r["subject"],
            "sender": r["sender"],
            "recipients": r["recipients"],
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "body": parsed.body,
            "attachments": parsed.attachments,
        })
    return out


def body() -> dict:
    return app.current_event.json_body or {}


def serialize(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: (str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None)))
                else v) for k, v in row.items()}


# --- accounts --------------------------------------------------------------

@app.get("/me")
def me():
    return serialize(current_user())


@app.get("/accounts")
def list_accounts():
    user = current_user()
    return [serialize(a) for a in repo.list_accounts(user["id"])]


@app.post("/accounts/gmail/connect")
def gmail_connect():
    """Returns the Google consent URL. `state` is a CSRF nonce generated and checked by the SPA."""
    state = body().get("state")
    if not state:
        raise BadRequestError("state is required")
    return {"auth_url": gmail.build_auth_url(state)}


@app.post("/accounts/gmail/callback")
def gmail_callback():
    """SPA posts the OAuth code here (with the user's JWT); we store tokens and start backfill."""
    user = current_user()
    code = body().get("code")
    if not code:
        raise BadRequestError("code is required")

    tokens = gmail.exchange_code(code)
    email_address = _gmail_address(tokens["access_token"])
    secret_arn = secrets.put_oauth_tokens(str(user["id"]), email_address, tokens)
    account = repo.create_account(user["id"], email_address, secret_arn)

    boto3.client("stepfunctions").start_execution(
        stateMachineArn=settings().backfill_state_machine_arn,
        input=json.dumps({"account_id": str(account["id"])}),
    )
    return serialize(account), 201


def _gmail_address(access_token: str) -> str:
    import httpx

    resp = httpx.get(
        f"{gmail.API}/profile", headers={"Authorization": f"Bearer {access_token}"}, timeout=15
    )
    resp.raise_for_status()
    return resp.json()["emailAddress"]


@app.delete("/accounts/<account_id>")
def disconnect_account(account_id: str):
    """Deletion on disconnect: tokens, raw mail in S3, and all derived rows (via FK cascade)."""
    user = current_user()
    account = require_account(user["id"], account_id)
    secrets.delete_secret(account["secret_arn"])
    storage.delete_prefix(f"users/{user['id']}/accounts/{account_id}/")
    repo.delete_account(user["id"], account_id)
    return {"deleted": account_id}


# --- inbox -----------------------------------------------------------------

@app.get("/accounts/<account_id>/threads")
def list_threads(account_id: str):
    user = current_user()
    require_account(user["id"], account_id)
    before = app.current_event.get_query_string_value("before")
    rows = repo.list_threads(
        user["id"], account_id, before=datetime.fromisoformat(before) if before else None
    )
    return [serialize(r) for r in rows]


@app.get("/accounts/<account_id>/threads/<thread_id>")
def get_thread(account_id: str, thread_id: str):
    user = current_user()
    require_account(user["id"], account_id)
    summary = repo.latest_summary(user["id"], account_id, thread_id)
    return {
        "emails": load_thread(user["id"], account_id, thread_id),
        "summary": serialize(summary),
    }


# --- AI features -----------------------------------------------------------

@app.post("/accounts/<account_id>/threads/<thread_id>/summary")
def summarize(account_id: str, thread_id: str):
    user = current_user()
    require_account(user["id"], account_id)
    content = llm.summarize_thread(load_thread(user["id"], account_id, thread_id))
    return serialize(
        repo.save_summary(user["id"], account_id, thread_id, content, settings().llm_model_id)
    )


@app.post("/accounts/<account_id>/threads/<thread_id>/draft")
def draft(account_id: str, thread_id: str):
    user = current_user()
    require_account(user["id"], account_id)
    b = body()
    tone, length = b.get("tone", "professional"), b.get("length", "short")
    content = llm.draft_reply(
        load_thread(user["id"], account_id, thread_id), tone, length, b.get("instructions", "")
    )
    return serialize(repo.save_draft(user["id"], account_id, thread_id, tone, length, content))


@app.post("/accounts/<account_id>/threads/<thread_id>/action-items")
def extract_action_items(account_id: str, thread_id: str):
    user = current_user()
    require_account(user["id"], account_id)
    items = llm.extract_action_items(load_thread(user["id"], account_id, thread_id))
    return [serialize(r) for r in repo.save_action_items(user["id"], account_id, thread_id, items)]


@app.get("/action-items")
def list_action_items():
    user = current_user()
    status = app.current_event.get_query_string_value("status")
    return [serialize(r) for r in repo.list_action_items(user["id"], status)]


@app.patch("/action-items/<item_id>")
def update_action_item(item_id: str):
    user = current_user()
    status = body().get("status")
    if status not in ("open", "done"):
        raise BadRequestError("status must be 'open' or 'done'")
    row = repo.set_action_item_status(user["id"], item_id, status)
    if not row:
        raise NotFoundError("action item not found")
    return serialize(row)


@app.post("/ask")
def ask():
    user = current_user()
    b = body()
    question = (b.get("question") or "").strip()
    if not question:
        raise BadRequestError("question is required")
    account_id = b.get("account_id")
    if account_id:
        require_account(user["id"], account_id)
    return rag.ask(str(user["id"]), question, account_id)


@app.exception_handler(llm.LLMRefusal)
def handle_refusal(ex: llm.LLMRefusal):
    from aws_lambda_powertools.event_handler import Response

    return Response(status_code=422, content_type="application/json",
                    body=json.dumps({"message": f"The AI model declined this request: {ex}"}))


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    return app.resolve(event, context)
