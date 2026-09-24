"""Application logging configuration.

Writes application logs (including the RAG document-retrieval pipeline) to a
rotating ``.log`` file.  Path, level and rotation limits come from Settings so
they can be overridden via environment variables (``LOG_DIR``, ``LOG_FILE``,
``LOG_LEVEL``, ``LOG_MAX_BYTES``, ``LOG_BACKUP_COUNT``).

Usage::

    setup_logging()
    logger = logging.getLogger("backend.app.rag")
    logger.info("retrieval started")
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.app.config import get_settings

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging() -> None:
    """Configure the root logger to write to the configured ``.log`` file.

    Idempotent: calling it more than once never adds a duplicate file handler,
    so it is safe to invoke from the FastAPI lifespan and/or module imports.
    """
    settings = get_settings()

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_path = Path(settings.log_dir) / settings.log_file

    # Ensure the target directory exists (mirrors _ensure_runtime_dirs).
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Attach the file handler only if it is not already wired up.
    if not any(
        isinstance(h, RotatingFileHandler)
        and Path(getattr(h, "baseFilename", "")) == log_path
        for h in root.handlers
    ):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

    # Prop our own loggers up to at least INFO so RAG messages show up, while
    # still letting the root level govern the overall filter. ChromaDB is very
    # chatty at INFO (every query logs internal telemetry) and would drown the
    # RAG pipeline in the rotating file, so it stays at WARNING unless the
    # configured level is stricter.
    for name in ("backend.app", "uvicorn"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = True
    chroma = logging.getLogger("chromadb")
    chroma.setLevel(min(level, logging.WARNING))
    chroma.propagate = True