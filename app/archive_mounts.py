from __future__ import annotations

import hashlib
import os
import re
import shutil
import unicodedata
from pathlib import Path, PurePosixPath

from app.config import (
    ARCHIVE_MOUNT_HOST_PATH,
    ARCHIVE_MOUNT_ROOT,
    ARCHIVE_MOUNTS_ENABLED,
)

_MOUNTINFO_ESCAPES = {
    r"\040": " ",
    r"\011": "\t",
    r"\012": "\n",
    r"\134": "\\",
}


def _decode_mountinfo_path(value: str) -> str:
    for encoded, decoded in _MOUNTINFO_ESCAPES.items():
        value = value.replace(encoded, decoded)
    return value


def _mountinfo_rows(path: str | Path = "/proc/self/mountinfo") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rows
    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        tail = after.split()
        if len(fields) < 6 or len(tail) < 3:
            continue
        try:
            mount_path = Path(_decode_mountinfo_path(fields[4]))
        except (TypeError, ValueError):
            continue
        rows.append({
            "path": mount_path,
            "optional": tuple(fields[6:]),
            "filesystem": tail[0],
            "source": tail[1],
        })
    return rows


def archive_mount_is_active(path: str | Path) -> bool:
    target = Path(path)
    for row in _mountinfo_rows():
        if row["path"] == target:
            filesystem = str(row.get("filesystem") or "")
            return filesystem.startswith("fuse")
    return False



def _fuse_user_allow_other_enabled(path: str | Path = "/etc/fuse.conf") -> bool:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        value = line.split("#", 1)[0].strip()
        if value == "user_allow_other":
            return True
    return False


def _cap_eff_has_sys_admin(status_path: str | Path = "/proc/self/status") -> bool:
    try:
        for line in Path(status_path).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("CapEff:"):
                value = int(line.split(":", 1)[1].strip(), 16)
                return bool(value & (1 << 21))
    except (OSError, ValueError):
        return False
    return False


def _mount_root_propagation() -> str:
    root = ARCHIVE_MOUNT_ROOT
    candidates: list[tuple[int, tuple[str, ...]]] = []
    for row in _mountinfo_rows():
        path = row["path"]
        if isinstance(path, Path) and (path == root or path in root.parents):
            candidates.append((len(path.parts), tuple(row.get("optional") or ())))
    if not candidates:
        return "unknown"
    optional = max(candidates, key=lambda item: item[0])[1]
    if any(item.startswith("shared:") for item in optional):
        return "shared"
    if any(item.startswith("master:") for item in optional):
        return "slave"
    return "private"


def archive_mount_capability() -> dict[str, object]:
    root = ARCHIVE_MOUNT_ROOT
    root_exists = root.is_dir()
    root_symlink = root.is_symlink()
    root_writable = root_exists and os.access(root, os.R_OK | os.W_OK | os.X_OK)
    fuse_device = Path("/dev/fuse").exists()
    fusermount = shutil.which("fusermount3") or shutil.which("fusermount")
    propagation = _mount_root_propagation() if root_exists else "missing"
    sys_admin = _cap_eff_has_sys_admin()
    allow_other = _fuse_user_allow_other_enabled()
    issues: list[str] = []
    if not ARCHIVE_MOUNTS_ENABLED:
        issues.append("Archiv-Mounts sind für diesen Container nicht aktiviert.")
    if not root.is_absolute():
        issues.append("BBM_ARCHIVE_MOUNT_ROOT muss ein absoluter Pfad sein.")
    if not root_exists:
        issues.append(f"Mount-Verzeichnis {root} ist nicht vorhanden.")
    elif root_symlink:
        issues.append(f"Mount-Verzeichnis {root} darf kein symbolischer Link sein.")
    elif not root_writable:
        issues.append(f"Mount-Verzeichnis {root} ist für den Borg-Benutzer nicht beschreibbar.")
    if not fuse_device:
        issues.append("/dev/fuse ist im Container nicht verfügbar.")
    if not fusermount:
        issues.append("fusermount3/fusermount ist im Container nicht verfügbar.")
    if not sys_admin:
        issues.append("Dem Container fehlt CAP_SYS_ADMIN.")
    if not allow_other:
        issues.append("/etc/fuse.conf erlaubt user_allow_other nicht.")
    if propagation != "shared":
        issues.append("Der Archiv-Mount-Pfad besitzt keine shared/rshared Mount-Propagation.")
    return {
        "enabled": ARCHIVE_MOUNTS_ENABLED,
        "ready": not issues,
        "container_path": str(root),
        "host_path": str(ARCHIVE_MOUNT_HOST_PATH) if ARCHIVE_MOUNT_HOST_PATH else None,
        "root_exists": root_exists,
        "root_writable": root_writable,
        "fuse_device": fuse_device,
        "fusermount": fusermount,
        "sys_admin": sys_admin,
        "allow_other": allow_other,
        "propagation": propagation,
        "issues": issues,
    }


def require_archive_mount_capability() -> dict[str, object]:
    capability = archive_mount_capability()
    if not capability["ready"]:
        raise ValueError(" ".join(str(item) for item in capability["issues"]))
    return capability


def _slug(value: str, *, fallback: str, max_length: int = 64) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(".-_")
    return (normalized[:max_length].rstrip(".-_") or fallback)


def archive_mount_path(repository_id: int, repository_name: str, archive: str) -> Path:
    if repository_id <= 0:
        raise ValueError("Repository must be persisted before an archive can be mounted")
    if not archive or archive.startswith("-") or "::" in archive or any(c in archive for c in "\x00\r\n/"):
        raise ValueError("Invalid archive name")
    root = ARCHIVE_MOUNT_ROOT
    if not root.is_absolute():
        raise ValueError("BBM_ARCHIVE_MOUNT_ROOT must be an absolute path")
    repository_component = f"{_slug(repository_name, fallback='repository')}-r{repository_id}"
    archive_hash = hashlib.sha256(archive.encode("utf-8")).hexdigest()[:12]
    archive_component = f"{_slug(archive, fallback='archive', max_length=80)}-{archive_hash}"
    path = root / repository_component / archive_component
    pure = PurePosixPath(str(path))
    if ".." in pure.parts:
        raise ValueError("Invalid archive mount path")
    return path


def prepare_archive_mount_path(path: str | Path) -> Path:
    target = Path(path)
    root = ARCHIVE_MOUNT_ROOT
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Archive mount root is unavailable or unsafe: {root}")
    root_resolved = root.resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Archive mount target is outside the configured root") from exc
    repository_dir = target.parent
    if repository_dir.exists() and repository_dir.is_symlink():
        raise ValueError("Archive mount repository directory must not be a symbolic link")
    repository_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if repository_dir.resolve(strict=True).parent != root_resolved:
        raise ValueError("Archive mount repository directory escaped the configured root")
    if target.exists() and target.is_symlink():
        raise ValueError("Archive mount target must not be a symbolic link")
    target.mkdir(mode=0o700, exist_ok=True)
    if target.resolve(strict=True).parent != repository_dir.resolve(strict=True):
        raise ValueError("Archive mount target escaped its repository directory")
    try:
        if any(target.iterdir()) and not archive_mount_is_active(target):
            raise ValueError("Archive mount target exists and is not empty")
    except OSError as exc:
        raise ValueError(f"Archive mount target could not be inspected: {exc}") from exc
    return target


def archive_mount_host_path(container_path: str | Path) -> str | None:
    if ARCHIVE_MOUNT_HOST_PATH is None:
        return None
    path = Path(container_path)
    try:
        relative = path.relative_to(ARCHIVE_MOUNT_ROOT)
    except ValueError:
        return None
    return str(ARCHIVE_MOUNT_HOST_PATH / relative)


def cleanup_archive_mount_path(path: str | Path) -> None:
    target = Path(path)
    try:
        target.relative_to(ARCHIVE_MOUNT_ROOT)
    except ValueError:
        return
    if archive_mount_is_active(target):
        return
    try:
        target.rmdir()
    except OSError:
        return
    try:
        target.parent.rmdir()
    except OSError:
        pass
