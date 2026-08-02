from __future__ import annotations

import configparser
import shutil
from pathlib import Path

from app.config import MANAGER_BORG_CACHE_DIR, REPOSITORY_ROOT
from app.models import Repository


_REPOSITORY_ID_LENGTH = 64


def managed_repository_id(repository: Repository) -> str:
    """Read and validate the Borg repository ID from a managed repository."""
    if not repository.storage_path:
        raise ValueError("Repository is not managed locally")
    root = REPOSITORY_ROOT.resolve()
    repository_path = Path(repository.storage_path).resolve()
    if repository_path == root or root not in repository_path.parents:
        raise ValueError("Repository path is outside the managed storage root")
    config_path = repository_path / "config"
    if not config_path.is_file():
        raise ValueError("Managed repository has no Borg config file")

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
        repository_id = parser.get("repository", "id").strip().lower()
    except (OSError, configparser.Error, KeyError, ValueError) as exc:
        raise ValueError("Borg repository ID could not be read from config") from exc
    if len(repository_id) != _REPOSITORY_ID_LENGTH or any(character not in "0123456789abcdef" for character in repository_id):
        raise ValueError("Borg repository config contains an invalid repository ID")
    return repository_id


def _path_size(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink() or path.is_file():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            total += child.lstat().st_size
        except OSError:
            continue
    return total



def manager_repository_cache_dir(repository: Repository) -> Path:
    """Return the manager-private Borg cache root for one repository record.

    Keeping each record below its own root prevents a stale cache lock from one
    repository action from blocking unrelated records and makes targeted cache
    cleanup possible without asking Borg to acquire the already-stale lock.
    """
    repository_id = int(repository.id or 0)
    if repository_id <= 0:
        raise ValueError("Repository must be persisted before its cache is used")
    root = MANAGER_BORG_CACHE_DIR.resolve()
    target = root / f"repository-{repository_id}"
    if target.parent.resolve() != root:
        raise ValueError("Unsafe manager Borg cache path")
    return target



def clear_repository_manager_cache_locks(repository: Repository) -> dict[str, int]:
    """Remove stale Borg cache locks from BBM's private manager cache only.

    Callers must serialize manager-side Borg commands for the repository before
    invoking this helper. The repository itself, cache contents and Borg
    security metadata are never modified. This is intended for stale
    ``lock.exclusive`` / ``lock.roster`` artifacts left after an interrupted
    manager-side command.
    """
    scoped = manager_repository_cache_dir(repository)
    removed_dirs = 0
    removed_files = 0
    if not scoped.is_dir():
        return {"lock_directories_removed": 0, "lock_files_removed": 0}
    try:
        entries = list(scoped.iterdir())
    except OSError:
        return {"lock_directories_removed": 0, "lock_files_removed": 0}
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            continue
        lock_dir = entry / "lock.exclusive"
        roster = entry / "lock.roster"
        try:
            if lock_dir.is_symlink() or lock_dir.is_file():
                lock_dir.unlink()
                removed_dirs += 1
            elif lock_dir.is_dir():
                shutil.rmtree(lock_dir)
                removed_dirs += 1
        except FileNotFoundError:
            pass
        try:
            if roster.is_symlink() or roster.is_file():
                roster.unlink()
                removed_files += 1
            elif roster.is_dir():
                shutil.rmtree(roster)
                removed_files += 1
        except FileNotFoundError:
            pass
    return {
        "lock_directories_removed": removed_dirs,
        "lock_files_removed": removed_files,
    }

def clear_repository_manager_cache(repository: Repository) -> dict[str, int | bool]:
    """Remove only the current manager-private cache for one repository record."""
    scoped = manager_repository_cache_dir(repository)
    removed = scoped.exists() or scoped.is_symlink()
    removed_bytes = _path_size(scoped) if removed else 0
    if removed:
        if scoped.is_symlink() or scoped.is_file():
            scoped.unlink()
        else:
            shutil.rmtree(scoped)
    return {
        "cache_removed": removed,
        "removed_bytes": removed_bytes,
    }

