import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from backend.app import llm, query_rewriting as rewriting


def test_independent_gemini_provider(monkeypatch):
    monkeypatch.setattr(rewriting, 'get_settings', lambda: SimpleNamespace(
        query_rewrite_provider='gemini', llm_provider='ollama',
        query_rewrite_model='gemini-2.5-flash', query_rewrite_timeout_seconds=15))
    factory = Mock()
    monkeypatch.setattr(rewriting, 'GeminiClient', factory)
    rewriting._client.cache_clear()
    try:
        rewriting._client()
        assert factory.call_args.kwargs['model'] == 'gemini-2.5-flash'
        assert factory.call_args.kwargs['response_schema']['additionalProperties'] is False
    finally:
        rewriting._client.cache_clear()


@pytest.mark.parametrize('failure', [None, 'blocked', 'empty', 'http', 'timeout'])
def test_gemini_request_and_errors(monkeypatch, failure):
    monkeypatch.setattr(llm, 'get_settings', lambda: SimpleNamespace(
        gemini_api_key='test-key', gemini_base_url='https://generativelanguage.googleapis.com/v1beta',
        llm_model='llama3.2'))
    real_client = httpx.Client
    captured = []
    def respond(request):
        captured.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('timeout', request=request)
        if failure == 'http':
            return httpx.Response(429)
        parts = [] if failure == 'empty' else [
            {'text': 'private reasoning', 'thought': True},
            {'text': '{"query":"Tôi nghỉ phép","clarification":""}'}]
        return httpx.Response(200, json={'candidates': [{
            'finishReason': 'SAFETY' if failure == 'blocked' else 'STOP',
            'content': {'parts': parts}}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))
    client = llm.GeminiClient(model='gemini-2.5-flash', response_schema=rewriting.Rewrite.model_json_schema())
    try:
        messages = [{'role': 'system', 'content': 'Rewrite only'},
                    {'role': 'user', 'content': 'toi nghi phep'}]
        if failure:
            with pytest.raises(llm.LLMError):
                client.complete(messages, temperature=0)
        else:
            assert rewriting.Rewrite.model_validate_json(client.complete(messages, temperature=0)).query == 'Tôi nghỉ phép'
        request = captured[0]
        assert str(request.url) == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
        assert request.headers['x-goog-api-key'] == 'test-key'
        payload = json.loads(request.content)
        assert payload['systemInstruction']['parts'] == [{'text': 'Rewrite only'}]
        assert payload['contents'] == [{'role': 'user', 'parts': [{'text': 'toi nghi phep'}]}]
        assert payload['generationConfig']['responseMimeType'] == 'application/json'
        assert payload['generationConfig']['responseJsonSchema']['additionalProperties'] is False
    finally:
        client._client.close()


def test_missing_gemini_key_falls_back(monkeypatch):
    from backend.app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, 'query_rewrite_enabled', True)
    monkeypatch.setattr(settings, 'query_rewrite_provider', 'gemini')
    monkeypatch.setattr(settings, 'gemini_api_key', '')
    rewriting._client.cache_clear()
    try:
        assert rewriting.rewrite_query('original question', []).query == 'original question'
    finally:
        rewriting._client.cache_clear()
