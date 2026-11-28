from types import SimpleNamespace

import pytest

from email_rag.services import queue


class _Sqs:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def send_message_batch(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


def _configure(monkeypatch, responses):
    client = _Sqs(responses)
    monkeypatch.setattr(queue, "_sqs", client)
    monkeypatch.setattr(queue, "settings", lambda: SimpleNamespace(ingest_queue_url="queue-url"))
    return client


def test_enqueue_retries_only_transiently_failed_entries(monkeypatch):
    client = _configure(
        monkeypatch,
        [
            {"Failed": [{"Id": "1", "SenderFault": False, "Code": "InternalError"}]},
            {},
        ],
    )

    assert queue.enqueue_messages("account-1", ["message-1", "message-2"]) == 2
    assert len(client.calls) == 2
    assert [entry["Id"] for entry in client.calls[1]["Entries"]] == ["1"]


def test_enqueue_raises_on_sender_fault(monkeypatch):
    _configure(
        monkeypatch,
        [{"Failed": [{"Id": "0", "SenderFault": True, "Code": "InvalidMessageContents"}]}],
    )

    with pytest.raises(RuntimeError, match="rejected"):
        queue.enqueue_messages("account-1", ["message-1"])
