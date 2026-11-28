"""Step Functions tasks for the initial backfill (diagram steps 10-11).

State machine: Start -> ListPage (loop while has more pages and under the cap) -> Finish.
Each step is short, so the 15-minute Lambda limit never applies to the whole backfill.
"""

import os
from datetime import UTC, datetime

from aws_lambda_powertools import Logger

from email_rag import repo
from email_rag.config import settings
from email_rag.services import queue
from email_rag.services.gmail import GmailClient

logger = Logger()
MAX_BACKFILL = int(os.environ.get("MAX_BACKFILL_MESSAGES", "2000"))


def start(event, _context):
    """Record the current historyId first so incremental sync picks up from here with no gap."""
    account = repo.get_account_by_id(event["account_id"])
    profile = GmailClient(account["secret_arn"]).profile()
    repo.update_sync_state(event["account_id"], history_id=str(profile["historyId"]))
    return {"account_id": event["account_id"], "page_token": None, "queued": 0, "done": False}


def list_page(event, _context):
    account = repo.get_account_by_id(event["account_id"])
    ids, next_token = GmailClient(account["secret_arn"]).list_message_ids(event["page_token"])
    queued = event["queued"] + queue.enqueue_messages(event["account_id"], ids)
    return {
        "account_id": event["account_id"],
        "page_token": next_token,
        "queued": queued,
        "done": next_token is None or queued >= MAX_BACKFILL,
    }


def finish(event, _context):
    account = repo.get_account_by_id(event["account_id"])
    watch_exp = None
    if settings().gmail_pubsub_topic:
        w = GmailClient(account["secret_arn"]).watch(settings().gmail_pubsub_topic)
        watch_exp = datetime.fromtimestamp(int(w["expiration"]) / 1000, tz=UTC)
    repo.update_sync_state(event["account_id"], status="active", watch_expiration=watch_exp)
    logger.info("backfill complete", extra=event)
    return event


def fail(event, _context):
    """Record terminal workflow failures so the UI does not show an endless backfill."""
    repo.update_sync_state(event["account_id"], status="error")
    logger.error("backfill failed", extra=event)
    return event


@logger.inject_lambda_context
def handler(event, context):
    step = event.get("step", "list_page")
    return {"start": start, "list_page": list_page, "finish": finish, "fail": fail}[step](
        event, context
    )
