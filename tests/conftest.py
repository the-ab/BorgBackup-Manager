from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Keep the test suite deterministic and ensure no runtime directories are ever
# created inside the release tree.
_TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="bbm-pytest-runtime-"))
os.environ.setdefault("BBM_DATA_DIR", str(_TEST_RUNTIME))
os.environ.setdefault("BBM_DATABASE_URL", f"sqlite:///{_TEST_RUNTIME / 'manager.db'}")
os.environ.setdefault("BBM_UPDATE_CHECK_ENABLED", "0")


def _cleanup_test_runtime() -> None:
    shutil.rmtree(_TEST_RUNTIME, ignore_errors=True)


atexit.register(_cleanup_test_runtime)
