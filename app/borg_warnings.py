from __future__ import annotations

import json
import re
from typing import Any

_STATUS_RE = re.compile(r"^\s*(?:(?i:Remote):\s*)?(?P<status>[CE])\s+(?P<path>.+?)\s*$")
_CHANGED_RE = re.compile(
    r"^(?:Remote:\s*)?(?:warning:\s*)?(?:backup:\s*)?(?P<path>.+?):\s*file changed while we backed it up\s*$",
    re.IGNORECASE,
)
_CHANGED_RE_ALT = re.compile(
    r"^(?:Remote:\s*)?(?:warning:\s*)?file changed while we backed it up:\s*(?P<path>.+?)\s*$",
    re.IGNORECASE,
)
_OPERATION_ERROR_RE = re.compile(
    r"^(?:Remote:\s*)?(?:warning:\s*)?(?P<operation>open|stat|lstat|read|scandir|listdir|access):\s*"
    r"(?P<path>.+?):\s*(?P<reason>(?:\[Errno\s+\d+\]\s*)?.+?)\s*$",
    re.IGNORECASE,
)
_PATH_ERRNO_RE = re.compile(
    r"^(?:Remote:\s*)?(?:warning:\s*)?(?P<path>.+?):\s*(?P<reason>\[Errno\s+\d+\]\s*.+?)\s*$",
    re.IGNORECASE,
)
_PYTHON_PATH_ERROR_RE = re.compile(
    r"^(?:PermissionError|OSError|FileNotFoundError):\s*(?P<reason>\[Errno\s+\d+\]\s*.+?):\s*[\"'](?P<path>.+?)[\"']\s*$",
    re.IGNORECASE,
)
_WARNING_PREFIX_RE = re.compile(r"^(?:Remote:\s*)?(?:warning|warning:|warn)\s*:?\s*(?P<message>.+?)\s*$", re.IGNORECASE)
_UNMATCHED_PATTERN_RE = re.compile(
    r"^(?:Remote:\s*)?(?P<message>(?:Include|Exclude) pattern .+? never matched\.?)\s*$",
    re.IGNORECASE,
)
_TERMINATION_RE = re.compile(r"terminating with (?:warning|success|error) status,\s*rc\s*\d+", re.IGNORECASE)
_COUNT_KEYS = ("changed", "permission", "missing", "io", "error", "other", "unknown")
_NON_WARNING_ITEM_STATUSES = frozenset("AMURdbchsfipx?+.-")
_NON_WARNING_ITEM_STATUS_BYTES = b"AMURdbchsfipx?+.-"
_ONLY_NON_WARNING_ITEM_BLOCK_BYTES_RE = re.compile(
    rb"(?:(?:[ \t]*(?:[Rr][Ee][Mm][Oo][Tt][Ee]:[ \t]*)?["
    + re.escape(_NON_WARNING_ITEM_STATUS_BYTES)
    + rb"][ \t]+[^\r\n]*\n))+\Z"
)


def _clean_path(value: str) -> str:
    return value.strip().strip("\"'")


def _kind_for_reason(reason: str) -> str:
    lower = reason.casefold()
    if "permission denied" in lower or "operation not permitted" in lower:
        return "permission"
    if "no such file or directory" in lower or "not found" in lower:
        return "missing"
    if "input/output error" in lower or "i/o error" in lower:
        return "io"
    return "error"


def _warning_item(line: str) -> dict[str, str] | None:
    line = line.strip()
    if not line or _TERMINATION_RE.search(line):
        return None

    status_match = _STATUS_RE.match(line)
    if status_match:
        status = status_match.group("status").upper()
        path = status_match.group("path")
        if status == "C":
            return {"kind": "changed", "path": _clean_path(path), "reason": "file changed while we backed it up"}
        return {"kind": "error", "path": _clean_path(path), "reason": "Borg reported a file access/read error"}

    changed_match = _CHANGED_RE.match(line) or _CHANGED_RE_ALT.match(line)
    if changed_match:
        return {
            "kind": "changed",
            "path": _clean_path(changed_match.group("path")),
            "reason": "file changed while we backed it up",
        }

    operation_match = _OPERATION_ERROR_RE.match(line)
    if operation_match:
        reason = operation_match.group("reason").strip()
        return {
            "kind": _kind_for_reason(reason),
            "path": _clean_path(operation_match.group("path")),
            "reason": f"{operation_match.group('operation')}: {reason}",
        }

    python_error_match = _PYTHON_PATH_ERROR_RE.match(line)
    if python_error_match:
        reason = python_error_match.group("reason").strip()
        return {
            "kind": _kind_for_reason(reason),
            "path": _clean_path(python_error_match.group("path")),
            "reason": reason,
        }

    errno_match = _PATH_ERRNO_RE.match(line)
    if errno_match:
        reason = errno_match.group("reason").strip()
        return {
            "kind": _kind_for_reason(reason),
            "path": _clean_path(errno_match.group("path")),
            "reason": reason,
        }

    warning_match = _WARNING_PREFIX_RE.match(line)
    if warning_match:
        message = warning_match.group("message").strip()
        if message and not _TERMINATION_RE.search(message):
            return {"kind": "other", "path": "", "reason": message}

    unmatched_match = _UNMATCHED_PATTERN_RE.match(line)
    if unmatched_match:
        return {"kind": "other", "path": "", "reason": unmatched_match.group("message").strip()}

    return None


def _can_skip_item_line(line: str) -> bool:
    """Fast-path ordinary ``borg create --list`` activity lines.

    Full file listings overwhelmingly consist of one status character, a space
    and a path. Only ``C`` and ``E`` can represent warning causes. Avoid running
    the complete regular-expression chain for all other item statuses.
    """
    candidate = line.lstrip()
    if candidate[:7].casefold() == "remote:":
        candidate = candidate[7:].lstrip()
    return (
        len(candidate) >= 2
        and candidate[0] in _NON_WARNING_ITEM_STATUSES
        and candidate[1].isspace()
    )


def _can_skip_item_line_bytes(line: bytes) -> bool:
    candidate = line.lstrip()
    if candidate[:7].lower() == b"remote:":
        candidate = candidate[7:].lstrip()
    return (
        len(candidate) >= 2
        and candidate[0] in _NON_WARNING_ITEM_STATUS_BYTES
        and chr(candidate[1]).isspace()
    )


def _empty_counts() -> dict[str, int]:
    return {kind: 0 for kind in _COUNT_KEYS}


class BorgWarningCollector:
    """Collect Borg warning causes before any output tail or log compaction.

    Subprocess output arrives in arbitrary chunks, and stdout/stderr chunks can
    interleave. Separate line buffers therefore prevent the end of one stream
    from being accidentally joined to the beginning of the other stream.
    """

    def __init__(self, *, max_items: int = 100):
        self.max_items = max(1, int(max_items))
        self._buffers: dict[str, bytes] = {"stdout": b"", "stderr": b""}
        self._items: list[dict[str, str]] = []
        self._seen: set[tuple[str, str, str]] = set()
        self._counts = _empty_counts()
        self._total_count = 0

    def _record(self, item: dict[str, str]) -> bool:
        kind = item.get("kind") or "other"
        path = _clean_path(item.get("path") or "")
        reason = (item.get("reason") or "").strip()
        key = (kind, path, reason)
        if key in self._seen:
            return False
        self._seen.add(key)
        self._total_count += 1
        self._counts[kind] = self._counts.get(kind, 0) + 1
        if len(self._items) < self.max_items:
            self._items.append({"kind": kind, "path": path, "reason": reason})
        return True

    def feed(self, text: str | None, *, stream: str = "stderr") -> bool:
        if not text:
            return False
        return self.feed_bytes(text.encode("utf-8", errors="replace"), stream=stream)

    def feed_bytes(self, data: bytes | bytearray | memoryview | None, *, stream: str = "stderr") -> bool:
        """Consume raw subprocess bytes without decoding ordinary file lists.

        A complete ``borg create --list`` block usually contains thousands of
        normal status/path lines. A bytes regex validates such a block in C and
        skips it as a whole. Only blocks containing C/E statuses or textual
        diagnostics are split and decoded line by line.
        """
        if not data:
            return False
        stream_name = stream if stream in self._buffers else "stderr"
        normalized = bytes(data).replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        combined = self._buffers[stream_name] + normalized
        newline = combined.rfind(b"\n")
        if newline < 0:
            self._buffers[stream_name] = combined
            return False
        complete = combined[: newline + 1]
        self._buffers[stream_name] = combined[newline + 1 :]
        if _ONLY_NON_WARNING_ITEM_BLOCK_BYTES_RE.fullmatch(complete):
            return False
        changed = False
        for raw_line in complete.splitlines():
            if _can_skip_item_line_bytes(raw_line):
                continue
            line = raw_line.decode("utf-8", errors="replace")
            item = _warning_item(line)
            if item is not None:
                changed = self._record(item) or changed
        return changed

    def finalize(self) -> bool:
        changed = False
        for stream, remainder in tuple(self._buffers.items()):
            if remainder:
                line = remainder.decode("utf-8", errors="replace")
                item = _warning_item(line)
                if item is not None:
                    changed = self._record(item) or changed
            self._buffers[stream] = b""
        return changed

    def summary(self) -> dict[str, Any] | None:
        if not self._total_count:
            return None
        result: dict[str, Any] = {
            "total_count": self._total_count,
            "items": list(self._items),
            "truncated_count": max(0, self._total_count - len(self._items)),
        }
        for kind in _COUNT_KEYS:
            result[f"{kind}_count"] = self._counts.get(kind, 0)
        return result


def parse_borg_warnings(text: str | None, *, max_items: int = 50) -> dict[str, Any] | None:
    """Extract concise, structured causes from an already available Borg log."""
    if not text:
        return None
    collector = BorgWarningCollector(max_items=max_items)
    collector.feed(text, stream="stderr")
    collector.finalize()
    return collector.summary()


def unresolved_warning_summary() -> dict[str, Any]:
    """Represent rc 1 honestly when Borg emitted no identifiable detail line."""
    reason = (
        "Borg returned warning status (rc 1), but no specific warning detail was present "
        "in the captured Borg output."
    )
    return {
        "total_count": 1,
        "changed_count": 0,
        "permission_count": 0,
        "missing_count": 0,
        "io_count": 0,
        "error_count": 0,
        "other_count": 0,
        "unknown_count": 1,
        "items": [{"kind": "unknown", "path": "", "reason": reason}],
        "truncated_count": 0,
        "unresolved": True,
    }


def warning_summary_from_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        return None
    try:
        total = int(parsed.get("total_count") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return parsed


def warning_diagnosis(summary: dict[str, Any] | None) -> dict[str, str] | None:
    """Return a compact German diagnosis for run lists and the detail header."""
    if not summary:
        return None
    if summary.get("unresolved") or int(summary.get("unknown_count") or 0):
        return {
            "title": "Borg meldete eine Warnung ohne Detailzeile",
            "detail": "Der Lauf endete mit RC 1, im von Borg ausgegebenen Text war jedoch keine konkrete Ursache enthalten.",
            "action": "Den vollständigen Lauf prüfen und den Backup-Job erneut beobachten. Bleibt die Ursache unbekannt, Borg auf dem Gerät aktualisieren und die Dateiliste testweise aktivieren.",
        }

    changed = int(summary.get("changed_count") or 0)
    unreadable = sum(int(summary.get(key) or 0) for key in ("permission_count", "missing_count", "io_count", "error_count"))
    other = int(summary.get("other_count") or 0)

    if changed and not unreadable and not other:
        noun = "Datei wurde" if changed == 1 else "Dateien wurden"
        return {
            "title": f"{changed} {noun} während der Sicherung verändert",
            "detail": "Das Archiv wurde erstellt, die genannten Dateien können aber einen inkonsistenten Zwischenstand enthalten.",
            "action": "Schreibintensive Anwendungen möglichst per Snapshot sichern oder während des Backups kurz anhalten.",
        }
    if unreadable and not changed and not other:
        noun = "Datei konnte" if unreadable == 1 else "Dateien konnten"
        return {
            "title": f"{unreadable} {noun} nicht vollständig gelesen werden",
            "detail": "Das Archiv wurde erstellt, die betroffenen Dateien fehlen jedoch möglicherweise oder wurden nur unvollständig übernommen.",
            "action": "Berechtigungen, verschwundene Pfade und mögliche I/O-Fehler prüfen; danach den Backup-Lauf wiederholen.",
        }
    return {
        "title": f"Backup mit {int(summary.get('total_count') or 0)} konkreten Warnhinweisen",
        "detail": "Das Archiv wurde gespeichert, enthält wegen der aufgeführten Warnungen aber möglicherweise nicht alle Daten konsistent oder vollständig.",
        "action": "Die Warnungsliste prüfen, Ursache beheben und den Backup-Lauf anschließend wiederholen.",
    }
