"""Worker Lambda (diagram steps 19-24): consume SQS, fetch -> S3 -> parse -> chunk -> embed -> index.

Uses partial batch responses: only failed records are retried; after maxReceiveCount they land
in the dead-letter queue, so one bad email never blocks the pipeline.
"""

import json

from aws_lambda_powertools import Logger

from email_rag import repo
from email_rag.services.gmail import GmailClient
from email_rag.services.ingest import ingest_message

logger = Logger()


@logger.inject_lambda_context
def handler(event, context):
    failures = []
    clients: dict[str, tuple[dict, GmailClient]] = {}
    for record in event["Records"]:
        try:
            msg = json.loads(record["body"])
            account_id = msg["account_id"]
            if account_id not in clients:
                account = repo.get_account_by_id(account_id)
                if account is None:  # account disconnected since enqueue: drop silently
                    continue
                clients[account_id] = (account, GmailClient(account["secret_arn"]))
            account, gmail = clients[account_id]
            ingest_message(account, gmail, msg["message_id"])
        except Exception:
            logger.exception("ingest failed", extra={"message_id": record["messageId"]})
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
