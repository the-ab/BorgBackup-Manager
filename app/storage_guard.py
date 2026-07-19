from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable


_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def _decode_mount_path(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def effective_storage_guard(repository: Any, settings: Any) -> tuple[bool, int, str]:
    """Return enabled, threshold and source for a repository storage guard."""
    repository_enabled = getattr(repository, "storage_guard_enabled", None)
    repository_threshold = getattr(repository, "storage_guard_threshold_percent", None)
    enabled = bool(settings.storage_guard_enabled) if repository_enabled is None else bool(repository_enabled)
    threshold = int(repository_threshold or settings.storage_guard_threshold_percent)
    source = "repository" if repository_enabled is not None or repository_threshold is not None else "global"
    return enabled, max(1, min(100, threshold)), source


def storage_usage(path: str | Path) -> dict[str, int | float]:
    target = Path(path)
    usage = shutil.disk_usage(target)
    percent = usage.used * 100 / usage.total if usage.total else 100.0
    return {
        "total": int(usage.total),
        "used": int(usage.used),
        "free": int(usage.free),
        "percent": round(percent, 1),
    }


def repository_storage_status(repository: Any, settings: Any) -> dict[str, Any] | None:
    path = getattr(repository, "storage_path", None)
    if not path:
        return None
    enabled, threshold, source = effective_storage_guard(repository, settings)
    usage = storage_usage(path)
    return {
        **usage,
        "path": str(Path(path)),
        "guard_enabled": enabled,
        "guard_threshold_percent": threshold,
        "guard_source": source,
        "guard_blocked": enabled and float(usage["percent"]) >= threshold,
    }


def mounted_filesystems_below(root: str | Path, mountinfo_path: str | Path = "/proc/self/mountinfo") -> list[Path]:
    """Return the repository root and every mount point visible below it."""
    root_path = Path(root).resolve()
    mounts: set[Path] = {root_path}
    try:
        lines = Path(mountinfo_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        before_separator = line.split(" - ", 1)[0].split()
        if len(before_separator) < 5:
            continue
        try:
            mount_path = Path(_decode_mount_path(before_separator[4])).resolve()
        except (OSError, ValueError):
            continue
        if mount_path == root_path or root_path in mount_path.parents:
            mounts.add(mount_path)

    # Some container/runtime combinations do not expose nested bind mounts as
    # separate mountinfo rows. Direct children with a different device still
    # identify independently mounted repository filesystems.
    try:
        root_device = root_path.stat().st_dev
        for child in root_path.iterdir():
            try:
                if child.is_dir() and (os.path.ismount(child) or child.stat().st_dev != root_device):
                    mounts.add(child.resolve())
            except OSError:
                continue
    except OSError:
        pass
    return sorted(mounts, key=lambda item: (len(item.parts), str(item)))


def _matching_mount(path: Path, mounts: Iterable[Path]) -> Path | None:
    candidates = [mount for mount in mounts if path == mount or mount in path.parents]
    return max(candidates, key=lambda item: len(item.parts), default=None)


def repository_storage_filesystems(
    repositories: Iterable[Any], root: str | Path, settings: Any,
    mountinfo_path: str | Path = "/proc/self/mountinfo",
) -> list[dict[str, Any]]:
    """Describe every repository filesystem and its effective guard rules."""
    mounts = mounted_filesystems_below(root, mountinfo_path)
    rows: dict[Path, dict[str, Any]] = {}
    for mount in mounts:
        try:
            usage = storage_usage(mount)
        except OSError:
            continue
        rows[mount] = {
            "path": str(mount),
            **usage,
            "repositories": [],
            "guard_blocked": False,
        }

    for repository in repositories:
        storage_path = getattr(repository, "storage_path", None)
        if not storage_path:
            continue
        try:
            resolved = Path(storage_path).resolve()
        except OSError:
            resolved = Path(storage_path)
        mount = _matching_mount(resolved, rows)
        if mount is None:
            try:
                usage = storage_usage(resolved)
            except OSError:
                continue
            mount = resolved
            rows[mount] = {
                "path": str(mount),
                **usage,
                "repositories": [],
                "guard_blocked": False,
            }
        enabled, threshold, source = effective_storage_guard(repository, settings)
        blocked = enabled and float(rows[mount]["percent"]) >= threshold
        rows[mount]["repositories"].append({
            "id": int(repository.id),
            "name": str(repository.name),
            "path": str(storage_path),
            "guard_enabled": enabled,
            "guard_threshold_percent": threshold,
            "guard_source": source,
            "guard_blocked": blocked,
        })
        rows[mount]["guard_blocked"] = bool(rows[mount]["guard_blocked"] or blocked)

    # An unassigned mount still uses the global setting for diagnostics.
    for row in rows.values():
        if not row["repositories"]:
            row["guard_enabled"] = bool(settings.storage_guard_enabled)
            row["guard_threshold_percent"] = int(settings.storage_guard_threshold_percent)
            row["guard_source"] = "global"
            row["guard_blocked"] = bool(
                row["guard_enabled"] and float(row["percent"]) >= row["guard_threshold_percent"]
            )
    return sorted(rows.values(), key=lambda item: item["path"])
