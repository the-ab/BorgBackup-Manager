from __future__ import annotations

from pathlib import Path

import pytest

import app.repository_cache as repository_cache
from app.models import Repository


def _write_repository_config(path: Path, repository_id: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config").write_text(
        f"[repository]\nversion = 1\nid = {repository_id}\n",
        encoding="utf-8",
    )


def test_managed_cache_clear_removes_only_current_repository_scoped_cache(monkeypatch, tmp_path: Path):
    current_cache = tmp_path / "data" / "borg-cache"
    monkeypatch.setattr(repository_cache, "MANAGER_BORG_CACHE_DIR", current_cache)
    repository = Repository(id=9, name="existing", location="/repositories/existing", storage_path="/repositories/existing")
    scoped = current_cache / "repository-9"
    other = current_cache / "repository-10"
    (scoped / ("a" * 64)).mkdir(parents=True)
    (scoped / ("a" * 64) / "config").write_text("remove", encoding="utf-8")
    other.mkdir(parents=True)
    (other / "config").write_text("keep", encoding="utf-8")

    result = repository_cache.clear_repository_manager_cache(repository)

    assert result["cache_removed"] is True
    assert result["removed_bytes"] > 0
    assert not scoped.exists()
    assert (other / "config").read_text(encoding="utf-8") == "keep"


def test_external_cache_clear_removes_repository_scoped_cache_without_borg_lock(monkeypatch, tmp_path: Path):
    current_cache = tmp_path / "data" / "borg-cache"
    monkeypatch.setattr(repository_cache, "MANAGER_BORG_CACHE_DIR", current_cache)
    repository = Repository(id=17, name="external", location="ssh://backup@example/./repo", storage_path=None)
    scoped = current_cache / "repository-17"
    (scoped / ("c" * 64) / "lock.exclusive").mkdir(parents=True)
    (scoped / ("c" * 64) / "lock.roster").write_text("stale", encoding="utf-8")

    result = repository_cache.clear_repository_manager_cache(repository)

    assert result["cache_removed"] is True
    assert result["removed_bytes"] > 0
    assert not scoped.exists()


def test_external_cache_lock_cleanup_preserves_cache_contents(monkeypatch, tmp_path: Path):
    current_cache = tmp_path / "data" / "borg-cache"
    monkeypatch.setattr(repository_cache, "MANAGER_BORG_CACHE_DIR", current_cache)
    repository = Repository(id=18, name="external", location="ssh://backup@example/./repo", storage_path=None)
    scoped = current_cache / "repository-18" / ("d" * 64)
    scoped.mkdir(parents=True)
    (scoped / "config").write_text("keep-cache", encoding="utf-8")
    (scoped / "chunks").write_text("keep-data", encoding="utf-8")
    (scoped / "lock.exclusive").mkdir()
    (scoped / "lock.roster").write_text("stale", encoding="utf-8")

    result = repository_cache.clear_repository_manager_cache_locks(repository)

    assert result == {"lock_directories_removed": 1, "lock_files_removed": 1}
    assert (scoped / "config").read_text(encoding="utf-8") == "keep-cache"
    assert (scoped / "chunks").read_text(encoding="utf-8") == "keep-data"
    assert not (scoped / "lock.exclusive").exists()
    assert not (scoped / "lock.roster").exists()
