from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from app.borg_stats import parse_borg_info
from app.config import REPOSITORY_ROOT
from app.database import SessionLocal
from app.models import Repository


def directory_size(path: Path) -> int:
    """Return logical file sizes without following symlinks."""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except (FileNotFoundError, PermissionError):
                    continue
    return total


def repository_statistics_from_borg_info(output: str) -> dict[str, int | None]:
    stats = parse_borg_info(output).get("repository", {})
    result = {
        "original_size": stats.get("original_size"),
        "compressed_size": stats.get("compressed_size"),
        "deduplicated_size": stats.get("deduplicated_size"),
    }
    if result["deduplicated_size"] is None:
        raise ValueError(
            "Borg hat keine repositoryweite deduplizierte Größe geliefert. "
            "Repository zuerst erfolgreich prüfen und Borg-Version kontrollieren."
        )
    return result


def store_repository_statistics(
    repository_id: int,
    *,
    filesystem_size: int | None = None,
    original_size: int | None = None,
    compressed_size: int | None = None,
    deduplicated_size: int | None = None,
) -> dict[str, int | None]:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        repository.original_size_bytes = None if original_size is None else max(0, int(original_size))
        repository.compressed_size_bytes = None if compressed_size is None else max(0, int(compressed_size))
        repository.deduplicated_size_bytes = None if deduplicated_size is None else max(0, int(deduplicated_size))
        # Existing dashboards use size_bytes as the closest physical/storage value:
        # local filesystem usage for managed repositories, Borg's repository-wide
        # deduplicated compressed data for remote repositories.
        if filesystem_size is not None:
            repository.size_bytes = max(0, int(filesystem_size))
        elif deduplicated_size is not None:
            repository.size_bytes = max(0, int(deduplicated_size))
        repository.size_checked_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "filesystem_size": None if filesystem_size is None else max(0, int(filesystem_size)),
            "original_size": repository.original_size_bytes,
            "compressed_size": repository.compressed_size_bytes,
            "deduplicated_size": repository.deduplicated_size_bytes,
            "size_bytes": repository.size_bytes,
        }


def managed_repository_filesystem_size(repository_id: int) -> int:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        if not repository.storage_path:
            raise ValueError("Lokale Größenberechnung ist nur für verwaltete Repositories verfügbar")
        root = REPOSITORY_ROOT.resolve()
        path = Path(repository.storage_path).resolve()
        if path != root and root not in path.parents:
            raise ValueError("Repository path is outside the managed storage root")
    return directory_size(path) if path.is_dir() else 0


