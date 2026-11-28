"""Sync Lambda (diagram steps 12-18): incremental sync via the Gmail History API.

Triggered by:
  * EventBridge Scheduler (periodic): syncs every active account and renews expiring watches.
  * API Gateway POST /webhooks/gmail (Gmail push via Google Cloud Pub/Sub): syncs one mailbox.
New message ids are put on the SQS ingestion queue for the Worker Lambda.
"""

import base64
import hmac
import json
from datetime import UTC, datetime, timedelta

import boto3
import httpx
from aws_lambda_powertools import Logger

from email_rag import repo
from email_rag.config import settings
from email_rag.services import queue, secrets
from email_rag.services.gmail import GmailClient

logger = Logger()


def sync_account(account: dict, renew_watch: bool = False) -> int:
    gmail = GmailClient(account["secret_arn"])
    account_id = str(account["id"])
    try:
        ids, latest = gmail.history_since(account["history_id"])
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:  # history id too old: needs a fresh backfill
            logger.warning("history expired", extra={"account_id": account_id})
            repo.update_sync_state(account_id, status="backfilling")
            boto3.client("stepfunctions").start_execution(
                stateMachineArn=settings().backfill_state_machine_arn,
                input=json.dumps({"account_id": account_id}),
            )
            return 0
        raise
    queued = queue.enqueue_messages(account_id, ids)

    watch_exp = None
    expiring = account["watch_expiration"] is None or account["watch_expiration"] < (
        datetime.now(UTC) + timedelta(days=1)
    )
    if renew_watch and expiring and settings().gmail_pubsub_topic:
        w = gmail.watch(settings().gmail_pubsub_topic)
        watch_exp = datetime.fromtimestamp(int(w["expiration"]) / 1000, tz=UTC)

    repo.update_sync_state(account_id, history_id=latest, watch_expiration=watch_exp)
    return queued


def _handle_webhook(event: dict) -> dict:
    token = (event.get("queryStringParameters") or {}).get("token", "")
    expected = secrets.get_cached_json(settings().webhook_secret_arn)["token"]
    if not hmac.compare_digest(token, expected):
        return {"statusCode": 403, "body": "forbidden"}

    push = json.loads(event.get("body") or "{}")
    data = json.loads(base64.b64decode(push["message"]["data"]))
    for account in repo.get_accounts_by_email(data["emailAddress"]):
        sync_account(account)
    # Always 2xx so Pub/Sub doesn't retry forever; the scheduled sync is the safety net.
    return {"statusCode": 204, "body": ""}


@logger.inject_lambda_context
def handler(event, context):
    if "httpMethod" in event:
        return _handle_webhook(event)

    total = 0
    for account in repo.list_active_accounts():
        try:
            total += sync_account(account, renew_watch=True)
        except Exception:
            logger.exception("sync failed", extra={"account_id": str(account["id"])})
    logger.info("scheduled sync complete", extra={"queued": total})
    return {"queued": total}
