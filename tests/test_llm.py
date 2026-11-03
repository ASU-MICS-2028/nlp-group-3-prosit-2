"""GeminiLLM falls back to the next model on 429/503, but not on other errors."""
import types as pytypes

import pytest
from google.genai import errors

from core.llm import GeminiLLM


def _llm(outcomes, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    llm = GeminiLLM(model="a")
    llm.models = ["a", "b", "c"]
    tried = []

    def generate_content(model, contents, config):
        tried.append(model)
        out = outcomes[model]
        if isinstance(out, Exception):
            raise out
        return pytypes.SimpleNamespace(text=out, usage_metadata=pytypes.SimpleNamespace(total_token_count=5))

    llm.client = pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(generate_content=generate_content))
    return llm, tried


def test_falls_back_on_quota_and_overload(monkeypatch):
    llm, tried = _llm({"a": errors.ClientError(429, {}), "b": errors.ServerError(503, {}), "c": "{}"}, monkeypatch)
    assert llm("sys", [{"role": "user", "content": "hi"}]) == "{}"
    assert tried == ["a", "b", "c"] and llm.model == "c" and llm.tokens == 5


def test_other_client_errors_raise(monkeypatch):
    llm, tried = _llm({"a": errors.ClientError(400, {}), "b": "{}", "c": "{}"}, monkeypatch)
    with pytest.raises(errors.ClientError):
        llm("sys", [{"role": "user", "content": "hi"}])
    assert tried == ["a"]


def test_extract_json_takes_first_object():
    from core.llm import extract_json
    assert extract_json('{"a": 1}\n{"b": 2}') == {"a": 1}
    assert extract_json('Sure:\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}
    with pytest.raises(ValueError):
        extract_json("no json here")
