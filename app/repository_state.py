from __future__ import annotations

from pathlib import Path

from app.config import REPOSITORY_ROOT
from app.models import Repository


def managed_repository_path(repository: Repository, *, require_directory: bool = True) -> Path:
    """Return a validated direct child below the managed repository root."""
    if not repository.storage_path:
        raise ValueError("Repository wird nicht lokal verwaltet")

    configured = Path(repository.storage_path)
    if configured.is_symlink():
        raise ValueError("Der Pfad eines verwalteten Repositorys darf kein symbolischer Link sein")

    root = REPOSITORY_ROOT.resolve()
    try:
        path = configured.resolve(strict=require_directory)
    except FileNotFoundError as exc:
        raise ValueError("Das verwaltete Repository-Verzeichnis ist nicht vorhanden") from exc
    except OSError as exc:
        raise ValueError(f"Der Pfad des verwalteten Repositorys kann nicht aufgelöst werden: {exc}") from exc

    if path == root or path.parent != root:
        raise ValueError("Repository-Pfad liegt außerhalb des verwalteten Speicherbereichs")
    if require_directory and not path.is_dir():
        raise ValueError("Der Pfad des verwalteten Repositorys ist kein Verzeichnis")
    return path


def managed_repository_present(repository: Repository) -> bool:
    """Return whether the configured managed path contains a Borg config file.

    This is a read-only state probe, so it intentionally does not enforce the
    destructive-operation containment rules used by reset and initialization.
    """
    if not repository.storage_path:
        return bool(repository.initialized)
    try:
        path = Path(repository.storage_path)
        return not path.is_symlink() and path.is_dir() and (path / "config").is_file()
    except OSError:
        return False


def require_empty_managed_repository(repository: Repository) -> Path:
    """Validate the only state in which manager metadata may be reset/init run."""
    path = managed_repository_path(repository)
    if (path / "config").exists():
        raise ValueError(
            "Repository-Verzeichnis enthält weiterhin eine Borg-Konfiguration; Zurücksetzen ist nicht zulässig"
        )
    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise ValueError(f"Repository-Verzeichnis kann nicht geprüft werden: {exc}") from exc
    if entries:
        preview = ", ".join(item.name for item in entries[:5])
        if len(entries) > 5:
            preview += f", … (+{len(entries) - 5})"
        raise ValueError(
            "Repository-Verzeichnis ist nicht leer. Es wurden keine Dateien gelöscht. "
            f"Vorhandene Einträge: {preview}"
        )
    return path


def require_initializable_managed_repository(repository: Repository) -> Path:
    """Validate a new/empty managed target without requiring it to exist yet."""
    path = managed_repository_path(repository, require_directory=False)
    if not path.exists():
        return path
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Der Pfad des verwalteten Repositorys ist kein Verzeichnis")
    if (path / "config").exists():
        raise ValueError("Repository-Verzeichnis enthält bereits eine Borg-Konfiguration")
    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise ValueError(f"Repository-Verzeichnis kann nicht geprüft werden: {exc}") from exc
    if entries:
        preview = ", ".join(item.name for item in entries[:5])
        if len(entries) > 5:
            preview += f", … (+{len(entries) - 5})"
        raise ValueError(
            "Repository-Verzeichnis ist nicht leer; Initialisierung wurde nicht gestartet. "
            f"Vorhandene Einträge: {preview}"
        )
    return path
