from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app import main, rag, query_rewriting as rewriting


@pytest.mark.parametrize('text', [
    "I couldn't find any information on the annual bonus payment schedule in the provided document excerpts.",
    'I have insufficient information to answer that question.',
    'Tôi không thể trả lời câu hỏi của bạn vì nó không liên quan đến nội dung được cung cấp.',
    'Tôi không đủ thông tin để trả lời câu hỏi này.',
    'Tôi không thể tìm thấy thông tin về công thức làm bánh trong tài liệu.',
])
def test_single_explicit_refusal(text):
    assert rag._is_refusal(text)


def test_rewrite_cannot_add_factory_or_change_numbers():
    assert not rewriting._preserves_words('Moi tuan duoc lam viec o nha may ngay?',
        'Mỗi tuần được làm việc ở nhà máy bao nhiêu ngày?', [])
    assert not rewriting._preserves_words('leave after 3 days', 'leave after 5 days', [])
    assert rewriting._preserves_words('o nha may ngay', 'Ở nhà mấy ngày?', [])


def test_followup_only_uses_existing_user_context():
    assert rewriting._preserves_words('How many days?', 'How many annual leave days?', ['annual leave'])
    assert not rewriting._preserves_words('How many days?', 'How many executive insurance days?', ['annual leave'])


def test_fusion_keeps_original_candidates():
    store = Mock()
    store.search_many.return_value = [
        [{'chunk_id': c, 'distance': .1} for c in 'ABCDE'],
        [{'chunk_id': c, 'distance': .2} for c in 'EFGHI'],
    ]
    hits = rewriting.retrieve_queries(store, 'original', 'rewrite', 'employee', 5)
    assert set('ABCDE') <= {h['chunk_id'] for h in hits}
    assert len(hits) == 9


@pytest.mark.parametrize('kind', ['sixth_chunk', 'orphan', 'inactive'])
def test_startup_rejects_index_drift(monkeypatch, kind):
    monkeypatch.setattr(main.settings, 'verify_index_on_startup', True)
    document = SimpleNamespace(id=1, is_active=kind != 'inactive',
        allowed_employee=False, allowed_hr=True, allowed_manager=True)
    db = Mock()
    db.scalars.return_value.all.return_value = [document]
    metadata = [dict(document_id='DOC_001', allow_employee=False, allow_hr=True, allow_manager=True) for _ in range(6)]
    if kind == 'sixth_chunk': metadata[-1]['allow_employee'] = True
    if kind == 'orphan': metadata[-1]['document_id'] = 'DOC_999'
    store = Mock()
    store._collection.get.return_value = {'metadatas': metadata}
    monkeypatch.setattr(main, 'get_vector_store', lambda: store)
    with pytest.raises(RuntimeError, match='permission drift'):
        main._check_index_permissions(db)


def test_startup_does_not_hide_store_failure(monkeypatch):
    monkeypatch.setattr(main.settings, 'verify_index_on_startup', True)
    monkeypatch.setattr(main, 'get_vector_store', Mock(side_effect=RuntimeError('offline')))
    with pytest.raises(RuntimeError, match='offline'):
        main._check_index_permissions(Mock())
