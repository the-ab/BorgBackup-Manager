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


def test_managed_cache_clear_removes_only_selected_current_and_legacy_cache(monkeypatch, tmp_path: Path):
    repository_root = tmp_path / "repositories"
    current_cache = tmp_path / "data" / "borg-cache"
    repository_id = "a" * 64
    other_id = "b" * 64
    repository_path = repository_root / "existing-repository"
    _write_repository_config(repository_path, repository_id)

    for root in (current_cache, repository_root / ".cache" / "borg"):
        (root / repository_id).mkdir(parents=True)
        (root / repository_id / "config").write_text("broken cache", encoding="utf-8")
        (root / other_id).mkdir(parents=True)
        (root / other_id / "config").write_text("keep", encoding="utf-8")

    monkeypatch.setattr(repository_cache, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(repository_cache, "MANAGER_BORG_CACHE_DIR", current_cache)
    repository = Repository(id=9, name="existing", location=str(repository_path), storage_path=str(repository_path))

    result = repository_cache.clear_managed_repository_cache(repository)

    assert result["repository_borg_id"] == repository_id
    assert result["cache_removed"] is True
    assert result["legacy_cache_removed"] is True
    assert result["removed_bytes"] > 0
    assert not (current_cache / repository_id).exists()
    assert not (repository_root / ".cache" / "borg" / repository_id).exists()
    assert (current_cache / other_id / "config").read_text(encoding="utf-8") == "keep"
    assert (repository_root / ".cache" / "borg" / other_id / "config").read_text(encoding="utf-8") == "keep"
    assert (repository_path / "config").is_file()


def test_managed_cache_clear_rejects_invalid_repository_id(monkeypatch, tmp_path: Path):
    repository_root = tmp_path / "repositories"
    repository_path = repository_root / "invalid"
    _write_repository_config(repository_path, "../../outside")
    monkeypatch.setattr(repository_cache, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(repository_cache, "MANAGER_BORG_CACHE_DIR", tmp_path / "cache")
    repository = Repository(id=10, name="invalid", location=str(repository_path), storage_path=str(repository_path))

    with pytest.raises(ValueError, match="invalid repository ID"):
        repository_cache.clear_managed_repository_cache(repository)


def test_external_cache_clear_removes_repository_scoped_cache_without_borg_lock(monkeypatch, tmp_path: Path):
    current_cache = tmp_path / "data" / "borg-cache"
    monkeypatch.setattr(repository_cache, "MANAGER_BORG_CACHE_DIR", current_cache)
    repository = Repository(id=17, name="external", location="ssh://backup@example/./repo", storage_path=None)
    scoped = current_cache / "repository-17"
    (scoped / ("c" * 64) / "lock.exclusive").mkdir(parents=True)
    (scoped / ("c" * 64) / "lock.roster").write_text("stale", encoding="utf-8")

    result = repository_cache.clear_repository_manager_cache(repository)

    assert result["repository_borg_id"] == "external"
    assert result["cache_removed"] is True
    assert result["removed_bytes"] > 0
    assert not scoped.exists()
