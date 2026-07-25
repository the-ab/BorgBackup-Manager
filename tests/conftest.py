from __future__ import annotations

import os

# Keep the test suite deterministic and independent of external services. These
# values are test-only and are never copied into runtime configuration.
os.environ.setdefault("BBM_ADMIN_TOKEN", "test-token")
os.environ.setdefault("BBM_ALLOW_LEGACY_TOKEN_AUTH", "1")
os.environ.setdefault("BBM_UPDATE_CHECK_ENABLED", "0")
