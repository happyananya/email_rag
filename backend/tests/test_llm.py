from types import SimpleNamespace

from email_rag.services import llm


def _fake_response(text: str = "ok"):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def test_complete_omits_effort_and_output_config_without_schema(monkeypatch):
    captured = {}

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _fake_response()

    monkeypatch.setattr(
        llm,
        "settings",
        lambda: SimpleNamespace(
            llm_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
    )
    monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(messages=Messages()))

    assert llm._complete("Summarize this") == "ok"
    assert captured["model"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert "output_config" not in captured


def test_complete_preserves_structured_output_for_action_items(monkeypatch):
    captured = {}

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _fake_response('{"items": []}')

    monkeypatch.setattr(
        llm,
        "settings",
        lambda: SimpleNamespace(
            llm_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
    )
    monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(messages=Messages()))

    schema = {"type": "object"}
    assert llm._complete("Extract tasks", schema=schema) == '{"items": []}'
    assert captured["output_config"] == {
        "format": {"type": "json_schema", "schema": schema}
    }
