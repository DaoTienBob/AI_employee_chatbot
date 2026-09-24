import os
import tempfile

# Isolation MUST happen before any backend.app module is imported: the SQLite
# engine, settings and runtime directories are all resolved at import time.
_TMP_DATA = tempfile.mkdtemp(prefix="chatbot_phase2_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DATA}/test.db"
os.environ["CHROMA_DIR"] = f"{_TMP_DATA}/chroma"
os.environ["UPLOAD_DIR"] = f"{_TMP_DATA}/uploads"
# Importing backend.app.rag calls setup_logging(); without this the test run
# appends to the developer's real data/logs/rag.log.
os.environ["LOG_DIR"] = f"{_TMP_DATA}/logs"

# Tests use the small cached model regardless of the developer model selection.
os.environ["EMBEDDING_PROVIDER"] = "minilm"
os.environ["EMBEDDING_MODEL"] = "all-MiniLM-L6-v2"
os.environ["EMBEDDING_QUERY_PREFIX"] = ""
os.environ["EMBEDDING_DOCUMENT_PREFIX"] = ""

# Deterministic tests; dedicated rewriting tests enable/mock the rewrite model.
os.environ["QUERY_REWRITE_ENABLED"] = "false"
