"""Document chunking (T06).

Splits cleaned section text into ~300-500 token chunks (token ≈ whitespace-
separated word, consistent with the sprint's approximation) and attaches the
source metadata required for citations and permission filtering (roadmap
§3.2): document_id, document_name, section, chunk_id and scalar role flags.
"""

import re
from dataclasses import dataclass

from backend.app.config import get_settings


@dataclass
class Chunk:
    """One indexed chunk with its source metadata."""

    chunk_id: str
    document_id: str
    document_name: str
    section: str
    text: str
    token_count: int
    allowed_roles: list[str]

    def metadata(self) -> dict[str, object]:
        """Scalar metadata for ChromaDB storage (roadmap §3.2 example)."""
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "section": self.section,
            "chunk_id": self.chunk_id,
            "allow_employee": "employee" in self.allowed_roles,
            "allow_hr": "hr" in self.allowed_roles,
            "allow_manager": "manager" in self.allowed_roles,
        }


def _split_into_token_windows(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping word windows of ~``size`` tokens.

    Splits on sentence boundaries where possible so chunks stay readable.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    windows: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence.split())
        # Single very long sentence: hard-split it by words.
        if sentence_len > size:
            if current:
                windows.append(" ".join(current))
                current, current_len = [], 0
            words = sentence.split()
            step = max(1, size - overlap)
            for start in range(0, len(words), step):
                window = words[start : start + size]
                if len(window) < overlap // 2 and windows and start > 0:
                    break
                windows.append(" ".join(window))
            continue

        if current_len + sentence_len > size and current:
            windows.append(" ".join(current))
            # Keep the tail as overlap for continuity.
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(current):
                prev_len = len(prev.split())
                if tail_len + prev_len > overlap:
                    break
                tail.insert(0, prev)
                tail_len += prev_len
            current, current_len = tail, tail_len

        current.append(sentence)
        current_len += sentence_len

    if current:
        windows.append(" ".join(current))
    return [w for w in windows if w.strip()]


def chunk_document(
    sections: list[tuple[str, str]],
    *,
    document_id: str,
    document_name: str,
    allowed_roles: list[str],
) -> list[Chunk]:
    """Chunk (section_title, section_text) pairs into indexed chunks.

    Args:
        sections: ``(section_title, section_text)`` pairs from parsing (T05).
        document_id: Stable document identifier (e.g. ``DOC_001``).
        document_name: Human-readable title for citations.
        allowed_roles: Roles permitted to see this document; inherited by
            every chunk (roadmap: "Every chunk inherits its parent document
            permissions").
    """
    settings = get_settings()
    size = max(50, settings.chunk_size_tokens)  # guard against silly config
    overlap = min(max(0, settings.chunk_overlap_tokens), size // 2)

    chunks: list[Chunk] = []
    counter = 0
    for section_title, section_text in sections:
        text = " ".join(section_text.split())
        if not text:
            continue
        for window in _split_into_token_windows(text, size, overlap):
            counter += 1
            chunks.append(
                Chunk(
                    # IDs must be unique across the whole collection (the
                    # vector store keys chunks by id), so the document id is
                    # part of the chunk id.
                    chunk_id=f"{document_id}_CHUNK_{counter:03d}",
                    document_id=document_id,
                    document_name=document_name,
                    section=section_title,
                    text=window,
                    token_count=len(window.split()),
                    allowed_roles=list(allowed_roles),
                )
            )

    # Keep section boundaries intact, including short final sections.
    return chunks
