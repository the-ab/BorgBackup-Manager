from __future__ import annotations

import re

_FILE_STATUS_RE = re.compile(r"^\s*([AMUCERdbchsfipx?+\-.])\s+\S")
_PERMISSION_ERROR_RE = re.compile(r"(?:PermissionError:\s*)?\[Errno 13\] Permission denied:\s*[\"\'][^\"\']+[\"\']", re.IGNORECASE)
_ERROR_MARKERS = (
    "error", "failed", "failure", "exception", "traceback", "permission denied",
    "connection closed", "connection refused", "timed out", "timeout", "no such file",
    "not found", "repository does not exist", "not a borg repository", "passphrase",
    "integrity", "lock timeout", "failed to create/acquire the lock", "read-only",
    "no space left", "disk full", "terminating with", "critical", "fatal", "invalid",
    "refused", "denied", "unreachable", "corrupt", "damaged", "unsupported",
    "cannot", "can't", "could not", "unable", "not available", "authentication",
    "host key verification failed", "network is unreachable", "broken pipe",
    "file changed while we backed it up", "errno",
)
_TRACE_CONTEXT_PREFIXES = (
    "file ", "platform:", "linux:", "borg:", "pid:", "cwd:", "sys.argv:",
    "ssh_original_command:", "during handling of the above exception", "the above exception",
)


def _is_file_activity(line: str) -> bool:
    """Return True for normal ``borg create --list`` status/path lines.

    Borg writes these lines to stderr by design. ``C`` and ``E`` are
    deliberately not treated as normal activity: ``C`` means that a file
    changed while it was read, while ``E`` represents a file-level error.
    """
    match = _FILE_STATUS_RE.match(line)
    return bool(match and match.group(1) not in {"C", "E"})


def extract_error_output(text: str | None) -> str:
    """Extract actual errors and warnings from Borg's stderr stream.

    Borg uses stderr for progress, file lists and final statistics. Presenting
    that raw stream as an error view is misleading, so the UI receives only
    diagnostic lines while the complete arrival-ordered output remains in the
    normal file-backed run log.
    """
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    permission_errors = _PERMISSION_ERROR_RE.findall(normalized)
    if permission_errors:
        # The complete traceback remains in the file-backed live log. The
        # dedicated error view only needs the actual filesystem cause.
        return permission_errors[-1]
    lines = normalized.splitlines()
    selected: list[str] = []
    traceback_mode = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        lower = stripped.lower()
        if not stripped:
            if selected and selected[-1] != "":
                selected.append("")
            continue
        if _is_file_activity(line):
            continue
        if "terminating with success status" in lower or lower in {"success", "rc 0"}:
            continue
        if lower.startswith("traceback (most recent call last):"):
            traceback_mode = True
            selected.append(line)
            continue
        if traceback_mode:
            # Python/Borg tracebacks end at the first non-indented exception
            # line; keep the following platform context as well.
            selected.append(line)
            if not line[:1].isspace() and ":" in line and not lower.startswith(_TRACE_CONTEXT_PREFIXES):
                traceback_mode = False
            continue
        status_match = _FILE_STATUS_RE.match(line)
        if status_match and status_match.group(1) in {"C", "E"}:
            selected.append(line)
            continue
        if any(marker in lower for marker in _ERROR_MARKERS):
            selected.append(line)
            continue
        if lower.startswith(_TRACE_CONTEXT_PREFIXES) and selected:
            selected.append(line)

    # Remove duplicate/leading/trailing blank lines and repeated identical
    # diagnostics that can be emitted by both SSH and Borg.
    cleaned: list[str] = []
    for line in selected:
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue
        if cleaned and cleaned[-1] == line:
            continue
        cleaned.append(line)
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)
