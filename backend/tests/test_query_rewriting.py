import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app import query_rewriting as rewriting
from backend.app.llm import LLMError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(rewriting, 'get_settings', lambda: SimpleNamespace(query_rewrite_enabled=True))
    client = Mock()
    monkeypatch.setattr(rewriting, '_client', lambda: client)
    return client


def test_rewrite_excludes_assistant_evidence(client):
    client.complete.return_value = json.dumps({'query': 'Tôi được nghỉ phép mấy ngày?', 'clarification': ''})
    result = rewriting.rewrite_query('toi duoc nghi phep may ngay', [
        {'role': 'user', 'content': 'Quy định nghỉ phép?'},
        {'role': 'assistant', 'content': 'SECRET OLD HR ANSWER'},
    ])
    assert result.query == 'Tôi được nghỉ phép mấy ngày?'
    messages = client.complete.call_args.args[0]
    assert 'SECRET' not in str(messages)
    assert 'Quy định nghỉ phép?' in str(messages)


@pytest.mark.parametrize('response', ['not json', '{}', '{"query":42,"clarification":""}',
    '{"query":"","clarification":""}', '{"query":"test","clarification":"which?"}',
    '{"query":"test","clarification":"","role":"hr"}'])
def test_invalid_rewrite_falls_back(client, response):
    client.complete.return_value = response
    assert rewriting.rewrite_query('original', []).query == 'original'


def test_timeout_falls_back(client):
    client.complete.side_effect = LLMError('timeout')
    assert rewriting.rewrite_query('original', []).query == 'original'


def test_clarification(client):
    client.complete.return_value = '{"query":"","clarification":"Nghỉ phép hay nghỉ việc?"}'
    assert rewriting.rewrite_query('xin nghi', []).clarification


def test_search_role_and_deduplication():
    store = Mock()
    def hit(id, distance):
        return {'chunk_id': id, 'distance': distance, 'text': id}
    store.search_many.return_value = [[hit('a', .2), hit('b', .3)], [hit('b', .1), hit('c', .2)]]
    result = rewriting.retrieve_queries(store, 'original', 'rewritten', 'employee', 3)
    assert [h['chunk_id'] for h in result] == ['b', 'a', 'c']
    assert result[0]['distance'] == .1
    store.search_many.assert_called_once_with(['original', 'rewritten'], 'employee', top_k=3)


def test_unchanged_query_searched_once():
    store = Mock()
    store.search_many.return_value = [[]]
    rewriting.retrieve_queries(store, 'original', 'original', 'manager', 5)
    # Deduplicated: one batched call, and the embedding batch has one query.
    store.search_many.assert_called_once_with(['original'], 'manager', top_k=5)


def test_oversized_rewrite_preserves_original_results():
    store = Mock()
    original = {'chunk_id': 'a', 'distance': .1}
    store.search_many.side_effect = ValueError('too long')
    store.search.return_value = [original]
    assert rewriting.retrieve_queries(store, 'original', 'long rewrite', 'hr', 5) == [original]
    store.search.assert_called_once_with('original', 'hr', top_k=5)


def test_refusal_reported_as_fallback_without_sources(monkeypatch):
    from backend.app import rag
    monkeypatch.setattr(rag, '_get_or_create_conversation', lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(rag, '_load_history', lambda *args: [])
    monkeypatch.setattr(rag, 'rewrite_query', lambda *args: rewriting.Rewrite(query='q', clarification=''))
    store = Mock()
    store.search_many.return_value = [[
        {'chunk_id': 'a', 'text': 'Some authorized text.', 'distance': .1,
         'metadata': {'document_name': 'policy', 'section': 'S'}}]]
    monkeypatch.setattr(rag, 'get_vector_store', lambda: store)
    llm = Mock()
    llm.complete.return_value = ('Tôi không thể trả lời. Không có thông tin về chủ đề này '
                                 'trong các tài liệu được cung cấp.')
    monkeypatch.setattr(rag, 'get_llm_client', lambda: llm)
    monkeypatch.setattr(rag, '_persist_messages', Mock())
    result = rag.answer_question('niche policy?', SimpleNamespace(id=1, role='employee'), Mock())
    assert result.fallback
    assert result.sources == []
    assert 'niche policy?' in result.answer or 'không' in result.answer.lower()


def test_refusal_threshold_requires_two_markers():
    from backend.app import rag
    assert rag._is_refusal('Không có thông tin về việc này. Không thể trả lời lúc này.') is True
    # A genuine answer quoting one negation stays a normal answer.
    assert rag._is_refusal('Nhân viên được nghỉ 12 ngày; overtime không được đề cập ở đây.') is False


def test_sources_capped_at_three(monkeypatch):
    from backend.app import rag
    monkeypatch.setattr(rag, '_get_or_create_conversation', lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(rag, '_load_history', lambda *args: [])
    monkeypatch.setattr(rag, 'rewrite_query', lambda *args: rewriting.Rewrite(query='q', clarification=''))
    store = Mock()
    store.search_many.return_value = [[
        {'chunk_id': c, 'text': f'text {c}', 'distance': .1 * i,
         'metadata': {'document_name': f'doc-{c}', 'section': 'S'}}
        for i, c in enumerate(['a', 'b', 'c', 'd', 'e'])]]
    monkeypatch.setattr(rag, 'get_vector_store', lambda: store)
    llm = Mock()
    llm.complete.return_value = 'Direct answer from the excerpts.'
    monkeypatch.setattr(rag, 'get_llm_client', lambda: llm)
    monkeypatch.setattr(rag, '_persist_messages', Mock())
    result = rag.answer_question('question?', SimpleNamespace(id=1, role='employee'), Mock())
    assert [s.document_name for s in result.sources] == ['doc-a', 'doc-b', 'doc-c']


def test_rag_does_not_replay_old_assistant_answer(monkeypatch):
    from backend.app import rag
    monkeypatch.setattr(rag, '_get_or_create_conversation', lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(rag, '_load_history', lambda *args: [
        {'role': 'user', 'content': 'leave policy'},
        {'role': 'assistant', 'content': 'OLD RESTRICTED CONTENT'},
    ])
    monkeypatch.setattr(rag, 'rewrite_query', lambda *args: rewriting.Rewrite(query='annual leave', clarification=''))
    store = Mock()
    store.search_many.return_value = [[
        {'chunk_id': 'a', 'text': 'Authorized leave policy.', 'distance': .1,
         'metadata': {'document_name': 'policy', 'section': 'Leave'}}]]
    monkeypatch.setattr(rag, 'get_vector_store', lambda: store)
    llm = Mock()
    llm.complete.return_value = 'Answer from current evidence'
    monkeypatch.setattr(rag, 'get_llm_client', lambda: llm)
    persist = Mock()
    monkeypatch.setattr(rag, '_persist_messages', persist)
    result = rag.answer_question('how many?', SimpleNamespace(id=1, role='employee'), Mock())
    assert not result.fallback
    assert 'OLD RESTRICTED' not in str(llm.complete.call_args)
    assert llm.complete.call_args.args[0][-1]['content'] == 'how many?'
    assert store.search_many.call_args.args[1] == 'employee'
    assert persist.call_args.args[1] == 'how many?'


def test_clarification_skips_retrieval_and_answer_generation(monkeypatch):
    from backend.app import rag
    monkeypatch.setattr(rag, '_get_or_create_conversation', lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(rag, '_load_history', lambda *args: [])
    monkeypatch.setattr(rag, 'rewrite_query', lambda *args: rewriting.Rewrite(query='', clarification='Leave or resignation?'))
    store, llm = Mock(), Mock()
    monkeypatch.setattr(rag, 'get_vector_store', store)
    monkeypatch.setattr(rag, 'get_llm_client', llm)
    monkeypatch.setattr(rag, '_persist_messages', Mock())
    result = rag.answer_question('nghi', SimpleNamespace(id=1, role='employee'), Mock())
    assert result.sources == [] and result.fallback
    store.assert_not_called()
    llm.assert_not_called()
