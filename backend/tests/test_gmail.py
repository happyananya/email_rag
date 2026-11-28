import httpx
import pytest

from email_rag.services import gmail


def _client(monkeypatch, responses):
    monkeypatch.setattr(gmail.secrets, "get_json", lambda _secret: {
        "access_token": "token", "expires_at": 4_000_000_000,
    })
    client = gmail.GmailClient("secret")
    queued = iter(responses)
    calls = []

    def handler(request):
        calls.append(request)
        status, body, headers = next(queued)
        return httpx.Response(status, json=body, headers=headers, request=request)

    client.http = httpx.Client(base_url=gmail.API, transport=httpx.MockTransport(handler))
    return client, calls


def _error(reason):
    return {"error": {"code": 403, "errors": [{"reason": reason}]}}


def test_get_retries_gmail_rate_limit_403(monkeypatch):
    client, calls = _client(monkeypatch, [
        (403, _error("userRateLimitExceeded"), {}),
        (200, {"id": "message-1"}, {}),
    ])
    sleeps = []
    monkeypatch.setattr(gmail.random, "uniform", lambda _start, _end: 0.25)
    monkeypatch.setattr(gmail.time, "sleep", sleeps.append)

    assert client._get("/messages/message-1") == {"id": "message-1"}
    assert len(calls) == 2
    assert sleeps == [1.25]


def test_get_honors_retry_after(monkeypatch):
    client, _calls = _client(monkeypatch, [
        (429, {"error": {"code": 429}}, {"Retry-After": "3"}),
        (200, {"ok": True}, {}),
    ])
    sleeps = []
    monkeypatch.setattr(gmail.time, "sleep", sleeps.append)

    assert client._get("/profile") == {"ok": True}
    assert sleeps == [3.0]


def test_get_does_not_retry_permanent_403(monkeypatch):
    client, calls = _client(monkeypatch, [(403, _error("insufficientPermissions"), {})])
    monkeypatch.setattr(
        gmail.time, "sleep", lambda _delay: (_ for _ in ()).throw(AssertionError("must not retry"))
    )

    with pytest.raises(httpx.HTTPStatusError):
        client._get("/messages/message-1")
    assert len(calls) == 1


def test_get_stops_after_max_attempts(monkeypatch):
    responses = [(503, {"error": {"code": 503}}, {})] * gmail.MAX_REQUEST_ATTEMPTS
    client, calls = _client(monkeypatch, responses)
    monkeypatch.setattr(gmail.random, "uniform", lambda _start, _end: 0)
    monkeypatch.setattr(gmail.time, "sleep", lambda _delay: None)

    with pytest.raises(httpx.HTTPStatusError):
        client._get("/messages/message-1")
    assert len(calls) == gmail.MAX_REQUEST_ATTEMPTS
