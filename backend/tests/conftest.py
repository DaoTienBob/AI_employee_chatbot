import os
import tempfile

# Isolation MUST happen before any backend.app module is imported: the SQLite
# engine, settings and runtime directories are all resolved at import time.
_TMP_DATA = tempfile.mkdtemp(prefix="chatbot_phase2_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DATA}/test.db"
os.environ["CHROMA_DIR"] = f"{_TMP_DATA}/chroma"
os.environ["UPLOAD_DIR"] = f"{_TMP_DATA}/uploads"
