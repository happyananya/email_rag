from types import SimpleNamespace

import pytest
from aws_lambda_powertools.event_handler.exceptions import BadRequestError

from email_rag.handlers import api


def _configure_summary(monkeypatch, cached):
    monkeypatch.setattr(api, "current_user", lambda: {"id": "user-1"})
    monkeypatch.setattr(api, "require_account", lambda *_args: {"id": "account-1"})
    monkeypatch.setattr(api, "settings", lambda: SimpleNamespace(llm_model_id="model-1"))
    monkeypatch.setattr(api.repo, "latest_summary", lambda *_args: cached)


def test_summarize_returns_fresh_cached_summary(monkeypatch):
    cached = {"id": "summary-1", "content": "Already summarized", "model": "model-1"}
    _configure_summary(monkeypatch, cached)
    monkeypatch.setattr(
        api, "load_thread", lambda *_args: (_ for _ in ()).throw(AssertionError("must not load"))
    )
    monkeypatch.setattr(
        api.llm,
        "summarize_thread",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not invoke Bedrock")),
    )

    assert api.summarize("account-1", "thread-1")["content"] == "Already summarized"


def test_summarize_generates_when_cache_is_stale(monkeypatch):
    _configure_summary(monkeypatch, None)
    monkeypatch.setattr(api, "load_thread", lambda *_args: [{"body": "New message"}])
    monkeypatch.setattr(api.llm, "summarize_thread", lambda _emails: "New summary")
    saved = []
    monkeypatch.setattr(
        api.repo,
        "save_summary",
        lambda *args: saved.append(args) or {"id": "summary-2", "content": args[3]},
    )

    result = api.summarize("account-1", "thread-1")

    assert result["content"] == "New summary"
    assert saved[0][3:] == ("New summary", "model-1")


def test_parse_before_requires_valid_timezone():
    with pytest.raises(BadRequestError, match="ISO 8601"):
        api.parse_before("not-a-date")
    with pytest.raises(BadRequestError, match="timezone"):
        api.parse_before("2026-11-27T10:00:00")

    parsed = api.parse_before("2026-11-27T10:00:00Z")
    assert parsed is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_draft_rejects_unsupported_tone_before_loading_thread(monkeypatch):
    monkeypatch.setattr(api, "current_user", lambda: {"id": "user-1"})
    monkeypatch.setattr(api, "require_account", lambda *_args: {"id": "account-1"})
    monkeypatch.setattr(api, "body", lambda: {"tone": "sarcastic", "length": "short"})
    monkeypatch.setattr(
        api, "load_thread", lambda *_args: (_ for _ in ()).throw(AssertionError("must not load"))
    )

    with pytest.raises(BadRequestError, match="tone must be one of"):
        api.draft("account-1", "thread-1")
