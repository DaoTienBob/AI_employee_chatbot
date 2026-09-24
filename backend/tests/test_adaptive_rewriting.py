from types import SimpleNamespace
from unittest.mock import Mock
import unicodedata

import pytest
from backend.app import query_rewriting as rw
from backend.scripts.benchmark_embeddings import CASES

@pytest.mark.parametrize('topic,vi,en', CASES)
def test_corpus_routes(topic, vi, en):
    assert rw.rewrite_reason(vi, []) == 'direct'
    assert rw.rewrite_reason(en, []) == 'direct'
    plain = ''.join(c for c in unicodedata.normalize('NFD', vi) if unicodedata.category(c) != 'Mn').replace('đ', 'd').replace('Đ', 'D')
    assert rw.rewrite_reason(plain, []) == 'unaccented_vietnamese'

@pytest.mark.parametrize('question,history,expected', [
    ('and next year?', [{'role':'user','content':'annual leave?'}], 'follow_up'),
    ('còn thử việc thì sao?', [{'role':'user','content':'nghỉ phép?'}], 'follow_up'),
    ('How do I request it?', [{'role':'user','content':'annual leave?'}], 'follow_up'),
    ('xin nghỉ', [], 'ambiguous_vietnamese'),
    ('nghi', [], 'ambiguous_vietnamese'),
    ('How many annual leave days do I get?', [{'role':'user','content':'WFH?'}], 'direct'),
    ('Can I request nghi phep online?', [], 'unaccented_vietnamese'),
    ('May I book a room?', [], 'direct'),
    ('How do I request it?', [{'role':'assistant','content':'annual leave'}], 'direct'),
    ('Tôi muốn xin nghi phep', [], 'unaccented_vietnamese'),
])
def test_additional_routes(question, history, expected):
    assert rw.rewrite_reason(question, history) == expected

@pytest.mark.parametrize('mode,enabled,question,calls', [
    ('adaptive', True, 'How many annual leave days do I get?', 0),
    ('adaptive', True, 'toi xin nghi phep', 1),
    ('always', True, 'How many annual leave days do I get?', 1),
    ('off', True, 'toi xin nghi phep', 0),
    ('adaptive', False, 'toi xin nghi phep', 0),
])
def test_mode_controls_calls(monkeypatch, mode, enabled, question, calls):
    monkeypatch.setattr(rw, 'get_settings', lambda: SimpleNamespace(query_rewrite_enabled=enabled, query_rewrite_mode=mode))
    client = Mock()
    client.complete.return_value = '{"query":"Tôi xin nghỉ phép","clarification":""}'
    monkeypatch.setattr(rw, '_client', lambda: client)
    result = rw.rewrite_query(question, [])
    assert client.complete.call_count == calls
    if not calls:
        assert result.query == question

@pytest.mark.parametrize('failure', ['timeout', 'malformed', 'changed_intent'])
def test_adaptive_failure_preserves_original(monkeypatch, failure):
    from backend.app.llm import LLMError
    monkeypatch.setattr(rw, 'get_settings', lambda: SimpleNamespace(query_rewrite_enabled=True, query_rewrite_mode='adaptive'))
    client = Mock()
    if failure == 'timeout':
        client.complete.side_effect = LLMError('timeout')
    else:
        client.complete.return_value = 'invalid JSON' if failure == 'malformed' else '{"query":"Tôi xin thôi việc","clarification":""}'
    monkeypatch.setattr(rw, '_client', lambda: client)
    assert rw.rewrite_query('toi xin nghi phep', []).query == 'toi xin nghi phep'
    client.complete.assert_called_once()
