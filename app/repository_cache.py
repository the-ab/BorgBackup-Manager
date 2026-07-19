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


def _remove_cache_entry(root: Path, repository_id: str) -> tuple[bool, int]:
    root = root.resolve()
    target = root / repository_id
    # The repository ID is validated to one hexadecimal path component. Keep an
    # explicit containment check as defence in depth before recursive deletion.
    resolved_parent = target.parent.resolve()
    if resolved_parent != root:
        raise ValueError("Unsafe Borg cache path")
    if not target.exists() and not target.is_symlink():
        return False, 0
    size = _path_size(target)
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)
    return True, size



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


def clear_repository_manager_cache(repository: Repository) -> dict[str, int | bool | str]:
    """Remove only manager-private cache data for one repository record.

    The repository itself and Borg security metadata are never touched. Legacy
    shared cache locations are cleaned for managed repositories when their Borg
    repository ID can be read locally; external legacy cache entries remain
    unused after the repository-scoped cache migration.
    """
    scoped = manager_repository_cache_dir(repository)
    scoped_removed = scoped.exists() or scoped.is_symlink()
    scoped_bytes = _path_size(scoped) if scoped_removed else 0
    if scoped_removed:
        if scoped.is_symlink() or scoped.is_file():
            scoped.unlink()
        else:
            shutil.rmtree(scoped)

    repository_id = "external"
    shared_removed = False
    shared_bytes = 0
    legacy_removed = False
    legacy_bytes = 0
    legacy_error = ""
    if repository.storage_path:
        try:
            repository_id = managed_repository_id(repository)
            shared_removed, shared_bytes = _remove_cache_entry(MANAGER_BORG_CACHE_DIR, repository_id)
            legacy_root = REPOSITORY_ROOT / ".cache" / "borg"
            legacy_removed, legacy_bytes = _remove_cache_entry(legacy_root, repository_id)
        except OSError as exc:
            legacy_error = str(exc)

    return {
        "repository_borg_id": repository_id,
        "cache_removed": scoped_removed or shared_removed,
        "legacy_cache_removed": legacy_removed,
        "legacy_cache_error": legacy_error,
        "removed_bytes": scoped_bytes + shared_bytes + legacy_bytes,
    }


def clear_managed_repository_cache(repository: Repository) -> dict[str, int | bool | str]:
    """Backward-compatible alias for repository-scoped manager cache cleanup."""
    if not repository.storage_path:
        raise ValueError("Repository is not managed locally")
    return clear_repository_manager_cache(repository)
