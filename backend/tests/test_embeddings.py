"""Provider contract, index separation, and truncation regression tests."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.embeddings import Embeddings


def adapter(provider='sentence_transformers', model='intfloat/multilingual-e5-base'):
    embedding = Embeddings.__new__(Embeddings)
    embedding.provider = provider
    embedding.model_name = model
    embedding.settings = SimpleNamespace(embedding_query_prefix='query: ', embedding_document_prefix='passage: ')
    return embedding


def test_prefixes_and_normalization():
    embedding = adapter()
    embedding.model = Mock(max_seq_length=512)
    embedding.model.tokenizer.encode.return_value = [1, 2, 3]
    embedding.model.encode.return_value.tolist.return_value = [[1.0, 0.0]]
    embedding.encode(['nghỉ phép'])
    embedding.model.encode.assert_called_with(['passage: nghỉ phép'], normalize_embeddings=True, show_progress_bar=False)
    embedding.encode(['annual leave'], query=True)
    embedding.model.encode.assert_called_with(['query: annual leave'], normalize_embeddings=True, show_progress_bar=False)


def test_models_and_prefixes_have_separate_collections():
    first = adapter()
    second = adapter(model='other-model')
    assert first.collection_name != second.collection_name
    second.model_name = first.model_name
    second.settings.embedding_query_prefix = ''
    assert first.collection_name != second.collection_name


def test_long_documents_split_without_dropping_words():
    embedding = adapter()
    embedding.model = Mock(max_seq_length=8)
    embedding.model.tokenizer.encode.side_effect = lambda text, **kwargs: text.split()
    text = ' '.join(f'word{i}' for i in range(30))
    pieces = embedding.split_passage(text)
    assert ' '.join(pieces) == text
    assert all(embedding.token_count('passage: '+piece) <= 8 for piece in pieces)
    with pytest.raises(ValueError, match='exceeds'):
        embedding.encode([text], query=True)


def test_ollama_never_silently_truncates():
    embedding = adapter(provider='ollama', model='bge-m3')
    embedding.settings.embedding_query_prefix = ''
    embedding.model = Mock()
    embedding.model.embed.return_value.embeddings = [[1.0]]
    assert embedding.encode(['xin chào'], query=True) == [[1.0]]
    embedding.model.embed.assert_called_once_with(model='bge-m3', input=['xin chào'], truncate=False)
