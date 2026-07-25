from __future__ import annotations

from pathlib import Path

from app.config import REPOSITORY_ROOT
from app.models import Repository


def managed_repository_path(repository: Repository, *, require_directory: bool = True) -> Path:
    """Return a validated repository path below the managed storage root.

    Imported repositories may live below mount/group directories such as
    ``/repositories/offline/nas-repo``.  Every path component is checked before
    resolution so symlinks cannot be used to escape or alias the managed root.
    """
    if not repository.storage_path:
        raise ValueError("Repository wird nicht lokal verwaltet")

    root = REPOSITORY_ROOT.resolve()
    configured = Path(repository.storage_path)
    try:
        relative = configured.relative_to(root)
    except ValueError as exc:
        raise ValueError("Repository-Pfad liegt außerhalb des verwalteten Speicherbereichs") from exc
    if not relative.parts:
        raise ValueError("Repository-Pfad darf nicht dem verwalteten Stammverzeichnis entsprechen")

    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise ValueError("Repository-Pfad enthält ein unsicheres Pfadsegment")
        current = current / part
        if current.is_symlink():
            raise ValueError("Der Pfad eines verwalteten Repositorys darf keine symbolischen Links enthalten")

    try:
        path = configured.resolve(strict=require_directory)
    except FileNotFoundError as exc:
        raise ValueError("Das verwaltete Repository-Verzeichnis ist nicht vorhanden") from exc
    except OSError as exc:
        raise ValueError(f"Der Pfad des verwalteten Repositorys kann nicht aufgelöst werden: {exc}") from exc

    if path == root or root not in path.parents:
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
