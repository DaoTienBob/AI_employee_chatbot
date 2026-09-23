"""Explicit document/query embeddings with configurable local providers."""
import hashlib
import json
from functools import cached_property, lru_cache

from backend.app.config import get_settings


class Embeddings:
    def __init__(self, settings):
        self.settings = settings
        self.provider = settings.embedding_provider
        self.model_name = settings.embedding_model
        if self.provider == 'sentence_transformers':
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(
                self.model_name, cache_folder=settings.embedding_cache_dir,
                device=settings.embedding_device,
            )
        elif self.provider == 'minilm':
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            if self.model_name != 'all-MiniLM-L6-v2':
                raise ValueError('minilm provider requires all-MiniLM-L6-v2')
            self.model = ONNXMiniLM_L6_V2()
        elif self.provider == 'ollama':
            from ollama import Client
            self.model = Client(host=settings.ollama_base_url, timeout=settings.embedding_timeout_seconds)
        else:
            raise ValueError(f'Unknown embedding provider: {self.provider}')

    @property
    def collection_name(self):
        # Never mix vector spaces, even when models have the same dimensions.
        identity = [self.provider, self.model_name,
                    self.settings.embedding_query_prefix, self.settings.embedding_document_prefix]
        digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
        return f'documents_{digest}'

    def token_count(self, text):
        if self.provider == 'sentence_transformers':
            return len(self.model.tokenizer.encode(text, truncation=False))
        if self.provider == 'minilm':
            return len(self.counting_tokenizer.encode(text).ids)
        return None  # Ollama validates the actual model context with truncate=False.

    @cached_property
    def counting_tokenizer(self):
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_str(self.model.tokenizer.to_str())
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return tokenizer

    @property
    def max_tokens(self):
        return self.model.max_seq_length if self.provider == 'sentence_transformers' else 256

    def split_passage(self, text):
        """Split oversized chunks without losing text or silently truncating it."""
        if self.provider == 'ollama':
            return [text]
        prefix = self.settings.embedding_document_prefix
        if self.token_count(prefix + text) <= self.max_tokens:
            return [text]
        words = text.split()
        if len(words) < 2:
            raise ValueError('A single word exceeds the embedding context window')
        midpoint = len(words) // 2
        return self.split_passage(' '.join(words[:midpoint])) + self.split_passage(' '.join(words[midpoint:]))

    def encode(self, texts, *, query=False):
        prefix = self.settings.embedding_query_prefix if query else self.settings.embedding_document_prefix
        inputs = [prefix + text for text in texts]
        if not inputs:
            return []
        if self.provider == 'ollama':
            return self.model.embed(model=self.model_name, input=inputs, truncate=False).embeddings
        if any(self.token_count(text) > self.max_tokens for text in inputs):
            raise ValueError('Input exceeds embedding model context; shorten the query or re-chunk the document')
        if self.provider == 'sentence_transformers':
            return self.model.encode(inputs, normalize_embeddings=True, show_progress_bar=False).tolist()
        return self.model(inputs)


@lru_cache
def get_embeddings():
    return Embeddings(get_settings())
