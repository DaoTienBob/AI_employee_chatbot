"""Stopping the backend must evict the Ollama models it loaded.

Ollama keeps model weights resident for ~5 minutes after the last request;
the shutdown hook sends ``keep_alive=0`` unload requests so stopping the
backend frees the RAM/VRAM immediately.
"""
import sys
import types

import httpx
import pytest

import backend.app.llm as llm
from backend.app.llm import OllamaClient, track_ollama_model, unload_ollama_models


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the used-model registry isolated between tests."""
    llm._used_ollama_models.clear()
    yield
    llm._used_ollama_models.clear()


def _fake_ollama_module(reply="ok"):
    module = types.ModuleType("ollama")

    class FakeClient:
        def __init__(self, host, timeout):
            self.host, self.timeout = host, timeout

        def chat(self, **kwargs):
            return {"message": {"content": f" {reply} "}}

    module.Client = FakeClient
    return module


def test_complete_tracks_the_ollama_model_for_unload(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama_module())
    client = OllamaClient(model="llama3.2")
    assert client.complete([{"role": "user", "content": "hi"}]) == "ok"
    assert ("http://localhost:11434", "llama3.2") in llm._used_ollama_models


def test_failed_completion_is_not_tracked(monkeypatch):
    fake = _fake_ollama_module()
    fake.Client.chat = lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setitem(sys.modules, "ollama", fake)
    client = OllamaClient(model="llama3.2")
    with pytest.raises(llm.LLMError):
        client.complete([{"role": "user", "content": "hi"}])
    assert llm._used_ollama_models == set()


def test_unload_sends_keep_alive_zero_for_each_tracked_model(monkeypatch):
    track_ollama_model("http://localhost:11434/", "llama3.2")
    track_ollama_model("http://localhost:11434", "nomic-embed-text:latest")
    sent = []
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, timeout=None: sent.append((url, json)))

    unloaded = unload_ollama_models()

    assert sorted(unloaded) == ["llama3.2", "nomic-embed-text:latest"]
    assert {payload["model"] for _, payload in sent} == {"llama3.2", "nomic-embed-text:latest"}
    for url, payload in sent:
        assert url == "http://localhost:11434/api/generate"
        assert payload["keep_alive"] == 0


def test_unload_is_safe_when_ollama_is_unreachable(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise httpx.ConnectError("ollama down")

    monkeypatch.setattr(httpx, "post", boom)
    track_ollama_model("http://localhost:11434", "llama3.2")
    assert unload_ollama_models() == []
    assert llm._used_ollama_models == set()


def test_unload_with_no_tracked_models_sends_no_requests(monkeypatch):
    # An unload request for a model that is NOT loaded would make Ollama
    # load it first, so unused models must never be contacted.
    sent = []
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, timeout=None: sent.append((url, json)))
    assert unload_ollama_models() == []
    assert sent == []


def test_ollama_embed_tracks_the_embedding_model(monkeypatch):
    settings = types.SimpleNamespace(
        embedding_provider="ollama", embedding_model="nomic-embed-text",
        ollama_base_url="http://localhost:11434", embedding_timeout_seconds=10.0,
        embedding_query_prefix="", embedding_document_prefix="",
    )
    from backend.app.embeddings import Embeddings

    fake = types.ModuleType("ollama")

    class FakeClient:
        def __init__(self, host, timeout):
            pass

        def embed(self, model, input, truncate):
            assert model == "nomic-embed-text"
            return types.SimpleNamespace(embeddings=[[0.1, 0.2]])

    fake.Client = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", fake)
    embeddings = Embeddings(settings)
    result = embeddings.encode(["hello"], query=True)
    assert result == [[0.1, 0.2]]
    assert ("http://localhost:11434", "nomic-embed-text") in llm._used_ollama_models
