from types import SimpleNamespace

import httpx

from email_rag.handlers import sync


class _ExpiredGmail:
    def __init__(self, _secret_arn):
        pass

    def history_since(self, _history_id):
        request = httpx.Request("GET", "https://gmail.test/history")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("expired", request=request, response=response)


class _StepFunctions:
    def __init__(self):
        self.calls = []

    def start_execution(self, **kwargs):
        self.calls.append(kwargs)


def test_expired_history_starts_fresh_backfill(monkeypatch):
    states = _StepFunctions()
    updates = []
    monkeypatch.setattr(sync, "GmailClient", _ExpiredGmail)
    monkeypatch.setattr(
        sync.repo, "update_sync_state", lambda *args, **kwargs: updates.append((args, kwargs))
    )
    monkeypatch.setattr(sync.boto3, "client", lambda service: states if service == "stepfunctions" else None)
    monkeypatch.setattr(
        sync,
        "settings",
        lambda: SimpleNamespace(backfill_state_machine_arn="arn:aws:states:test", gmail_pubsub_topic=""),
    )

    result = sync.sync_account(
        {
            "id": "account-1",
            "secret_arn": "secret",
            "history_id": "old",
            "watch_expiration": None,
        }
    )

    assert result == 0
    assert updates == [(('account-1',), {"status": "backfilling"})]
    assert states.calls[0]["stateMachineArn"] == "arn:aws:states:test"
    assert '"account_id": "account-1"' in states.calls[0]["input"]
