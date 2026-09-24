import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from backend.app import llm, query_rewriting as rewriting


def test_rewrite_provider_independent_of_answer_provider(monkeypatch):
    settings = SimpleNamespace(query_rewrite_provider='openai', llm_provider='ollama',
        query_rewrite_model='gpt-4.1-mini', query_rewrite_timeout_seconds=15)
    monkeypatch.setattr(rewriting, 'get_settings', lambda: settings)
    factory = Mock()
    monkeypatch.setattr(rewriting, 'OpenAIClient', factory)
    rewriting._client.cache_clear()
    try:
        rewriting._client()
        assert factory.call_args.kwargs['model'] == 'gpt-4.1-mini'
        assert factory.call_args.kwargs['response_schema']['additionalProperties'] is False
    finally:
        rewriting._client.cache_clear()


def test_openai_request_uses_strict_schema(monkeypatch):
    monkeypatch.setattr(llm, 'get_settings', lambda: SimpleNamespace(
        openai_api_key='test-key', openai_base_url='https://api.openai.com/v1', llm_model='llama3.2'))
    captured = []
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content':
            '{"query":"Tôi nghỉ phép","clarification":""}'}}]})
    client = llm.OpenAIClient(model='gpt-4.1-mini', response_schema=rewriting.Rewrite.model_json_schema())
    client._client.close()
    client._client = httpx.Client(base_url='https://api.openai.com/v1', transport=httpx.MockTransport(respond))
    try:
        result = client.complete([{'role': 'user', 'content': 'toi nghi phep'}], temperature=0)
        assert rewriting.Rewrite.model_validate_json(result).query == 'Tôi nghỉ phép'
        payload = json.loads(captured[0].content)
        assert str(captured[0].url) == 'https://api.openai.com/v1/chat/completions'
        assert payload['model'] == 'gpt-4.1-mini'
        assert payload['response_format']['json_schema']['strict'] is True
        assert payload['store'] is False
    finally:
        client._client.close()


def test_missing_api_key_falls_back_to_original(monkeypatch):
    from backend.app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, 'query_rewrite_enabled', True)
    monkeypatch.setattr(settings, 'query_rewrite_provider', 'openai')
    monkeypatch.setattr(settings, 'openai_api_key', '')
    rewriting._client.cache_clear()
    try:
        assert rewriting.rewrite_query('original question', []).query == 'original question'
    finally:
        rewriting._client.cache_clear()
