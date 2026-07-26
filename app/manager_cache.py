from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import MANAGER_BORG_CACHE_DIR, MANAGER_BORG_SECURITY_DIR
from app.database import SessionLocal
from app.models import Repository
from app.repository_cache import managed_repository_id

_HEX_ID = re.compile(r"^[0-9a-f]{64}$")
_SCOPED_CACHE = re.compile(r"^repository-([1-9][0-9]*)$")


def _tree_size(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink() or path.is_file():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            for child in current.iterdir():
                try:
                    if child.is_symlink():
                        total += child.lstat().st_size
                    elif child.is_dir():
                        stack.append(child)
                    elif child.is_file():
                        total += child.stat().st_size
                except OSError:
                    continue
        except OSError:
            continue
    return total


def _normalize_location(value: str | None) -> str:
    text = (value or "").strip().rstrip("/")
    if text.startswith("file://"):
        text = text[7:].rstrip("/")
    return text


def _normalized_locations(repository: Repository) -> set[str]:
    return {
        normalized
        for raw in (repository.location, repository.storage_path)
        if (normalized := _normalize_location(raw))
    }


def _read_small_text(path: Path, filename: str) -> str:
    target = path / filename
    if not target.is_file() or target.is_symlink():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _security_location(path: Path) -> str:
    return _normalize_location(_read_small_text(path, "location"))


def _security_manifest_timestamp(path: Path) -> str:
    return _read_small_text(path, "manifest-timestamp")


def _parse_manifest_timestamp(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_context() -> tuple[set[int], set[str], set[str]]:
    with SessionLocal() as db:
        repositories = list(db.scalars(select(Repository).order_by(Repository.id)).all())
    manager_ids = {int(repository.id) for repository in repositories if repository.id is not None}
    locations: set[str] = set()
    borg_ids: set[str] = set()
    for repository in repositories:
        locations.update(_normalized_locations(repository))
        if repository.storage_path:
            try:
                borg_ids.add(managed_repository_id(repository))
            except (OSError, ValueError):
                pass
        if repository.id is not None:
            scoped = MANAGER_BORG_CACHE_DIR / f"repository-{int(repository.id)}"
            if scoped.is_dir() and not scoped.is_symlink():
                try:
                    for child in scoped.iterdir():
                        if child.is_dir() and not child.is_symlink() and _HEX_ID.fullmatch(child.name):
                            borg_ids.add(child.name)
                except OSError:
                    pass
    return manager_ids, locations, borg_ids


def manager_borg_cache_status() -> dict:
    """Inspect manager cache and manager-side Borg security state without changing data."""
    MANAGER_BORG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MANAGER_BORG_SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    manager_ids, locations, borg_ids = _active_context()
    items: list[dict] = []

    try:
        cache_entries = list(MANAGER_BORG_CACHE_DIR.iterdir())
    except OSError:
        cache_entries = []
    for entry in cache_entries:
        if entry.is_symlink():
            continue
        scoped_match = _SCOPED_CACHE.fullmatch(entry.name)
        if scoped_match and entry.is_dir():
            repository_id = int(scoped_match.group(1))
            if repository_id not in manager_ids:
                items.append({
                    "kind": "manager_cache_orphan",
                    "entry_type": "manager_cache",
                    "label": f"Manager-Cache Repository #{repository_id}",
                    "name": entry.name,
                    "path": str(entry),
                    "size_bytes": _tree_size(entry),
                    "selectable": True,
                    "default_selected": True,
                    "reason": "Kein Repository mit dieser Manager-ID vorhanden.",
                })
            continue
        if entry.is_dir() and _HEX_ID.fullmatch(entry.name) and entry.name not in borg_ids:
            security_location = _security_location(MANAGER_BORG_SECURITY_DIR / entry.name)
            if security_location and security_location in locations:
                continue
            items.append({
                "kind": "legacy_cache_orphan",
                "entry_type": "manager_cache",
                "label": f"Legacy-Borg-Cache {entry.name[:12]}…",
                "name": entry.name,
                "path": str(entry),
                "size_bytes": _tree_size(entry),
                "selectable": True,
                "default_selected": True,
                "reason": "Borg-Repository-ID ist keinem aktuellen Repository zugeordnet.",
            })

    security_items: list[dict] = []
    try:
        security_entries = list(MANAGER_BORG_SECURITY_DIR.iterdir())
    except OSError:
        security_entries = []
    for entry in security_entries:
        valid_id = bool(_HEX_ID.fullmatch(entry.name))
        if entry.is_symlink() or not entry.is_dir() or not valid_id:
            security_items.append({
                "kind": "manager_security_unknown",
                "entry_type": "manager_security",
                "label": f"Unbekannter Borg-Sicherheitsstatus {entry.name}",
                "name": entry.name,
                "path": str(entry),
                "size_bytes": _tree_size(entry),
                "location": "",
                "manifest_timestamp": "",
                "selectable": False,
                "default_selected": False,
                "reason": "Kein reguläres 64-stelliges Borg-Security-Verzeichnis; wird nicht zur Löschung freigegeben.",
            })
            continue
        location = _security_location(entry)
        manifest_timestamp = _security_manifest_timestamp(entry)
        manifest_dt = _parse_manifest_timestamp(manifest_timestamp)
        active = entry.name in borg_ids or (location and location in locations)
        security_items.append({
            "kind": "manager_security_active" if active else "manager_security_orphan",
            "entry_type": "manager_security",
            "label": f"Borg-Sicherheitsstatus {entry.name[:12]}…",
            "name": entry.name,
            "path": str(entry),
            "size_bytes": _tree_size(entry),
            "location": location,
            "manifest_timestamp": manifest_timestamp,
            "manifest_timestamp_utc": manifest_dt.isoformat() if manifest_dt else None,
            "selectable": not active,
            "default_selected": not active,
            "reason": (
                "Repository-ID oder gespeicherter Repository-Standort ist einem aktuellen BBM-Repository zugeordnet."
                if active else
                (f"Gespeicherter Repository-Pfad ist nicht mehr zugeordnet: {location}" if location else
                 "Repository-ID und Sicherheitsstatus sind keinem aktuellen BBM-Repository zugeordnet.")
            ),
        })

    by_location: dict[str, list[dict]] = {}
    for item in security_items:
        if item.get("location") and item.get("manifest_timestamp_utc") and item.get("name"):
            by_location.setdefault(str(item["location"]), []).append(item)
    for location, group in by_location.items():
        if len(group) < 2:
            continue
        dated = [(item, _parse_manifest_timestamp(item.get("manifest_timestamp"))) for item in group]
        dated = [(item, stamp) for item, stamp in dated if stamp is not None]
        if len(dated) < 2:
            for item in group:
                item["duplicate_state"] = "ambiguous"
                item["reason"] += " Mehrere Manager-Security-Verzeichnisse verwenden denselben Standort, die manifest-timestamp-Werte sind aber nicht eindeutig vergleichbar."
            continue
        newest_stamp = max(stamp for _item, stamp in dated)
        newest = [item for item, stamp in dated if stamp == newest_stamp]
        if len(newest) != 1:
            for item in group:
                item["duplicate_state"] = "ambiguous"
                item["reason"] += " Mehrere Manager-Security-Verzeichnisse verwenden denselben Standort und denselben neuesten manifest-timestamp."
            continue
        newest_item = newest[0]
        newest_item["duplicate_state"] = "newest"
        newest_item["duplicate_newest_id"] = newest_item.get("name")
        for item, _stamp in dated:
            if item is newest_item:
                continue
            item["duplicate_state"] = "older"
            item["duplicate_newest_id"] = newest_item.get("name")
            if item.get("kind") == "manager_security_active" and item.get("name") in borg_ids:
                item["reason"] += " Für denselben Standort existiert ein Security-Stand mit neuerem manifest-timestamp; die Borg-ID ist jedoch über den aktiven Manager-Cache bestätigt und bleibt deshalb geschützt."
                item["selectable"] = False
                item["default_selected"] = False
            else:
                item["kind"] = "manager_security_duplicate_old"
                item["selectable"] = True
                item["default_selected"] = True
                item["reason"] = (
                    f"Älterer Manager-Borg-Sicherheitsstatus für denselben Repository-Standort; neuerer Stand: "
                    f"{newest_item.get('name')} ({newest_item.get('manifest_timestamp') or 'ohne Zeitstempel'})."
                )

    items.extend(security_items)
    selectable = [item for item in items if item.get("selectable")]
    orphan_bytes = sum(int(item["size_bytes"]) for item in selectable)
    return {
        "cache_path": str(MANAGER_BORG_CACHE_DIR),
        "security_path": str(MANAGER_BORG_SECURITY_DIR),
        "cache_size_bytes": _tree_size(MANAGER_BORG_CACHE_DIR),
        "security_size_bytes": _tree_size(MANAGER_BORG_SECURITY_DIR),
        "orphan_count": len(selectable),
        "orphan_size_bytes": orphan_bytes,
        "security_active_count": sum(1 for item in security_items if item.get("kind") == "manager_security_active"),
        "security_orphan_count": sum(1 for item in security_items if item.get("kind") == "manager_security_orphan"),
        "security_duplicate_old_count": sum(1 for item in security_items if item.get("kind") == "manager_security_duplicate_old"),
        "security_unknown_count": sum(1 for item in security_items if item.get("kind") == "manager_security_unknown"),
        "items": items,
    }


def _safe_remove(path: Path, root: Path) -> int:
    root_resolved = root.resolve()
    candidate = path.resolve(strict=False)
    if candidate == root_resolved or root_resolved not in candidate.parents:
        raise ValueError("Unsicherer Borg-Cache-Bereinigungspfad")
    size = _tree_size(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    return size


def cleanup_orphaned_manager_borg_data(requested_paths: list[str] | None = None) -> dict:
    """Re-scan and remove only selected entries that are still safely deletable."""
    before = manager_borg_cache_status()
    candidates = {str(item["path"]): item for item in before["items"] if item.get("selectable")}
    selected = [str(value) for value in (requested_paths or list(candidates))]
    removed_count = 0
    removed_bytes = 0
    skipped: list[dict] = []
    cache_root = MANAGER_BORG_CACHE_DIR.resolve()
    security_root = MANAGER_BORG_SECURITY_DIR.resolve()
    for raw_path in selected:
        item = candidates.get(raw_path)
        if item is None:
            skipped.append({"path": raw_path, "reason": "Eintrag ist nicht mehr zur Bereinigung freigegeben."})
            continue
        path = Path(item["path"])
        root = security_root if item.get("entry_type") == "manager_security" else cache_root
        if not path.exists() and not path.is_symlink():
            skipped.append({"path": str(path), "reason": "Eintrag existiert nicht mehr."})
            continue
        removed_bytes += _safe_remove(path, root)
        removed_count += 1
    after = manager_borg_cache_status()
    return {
        "removed_count": removed_count,
        "removed_bytes": removed_bytes,
        "skipped": skipped,
        "remaining_orphan_count": after["orphan_count"],
        "status": after,
    }
