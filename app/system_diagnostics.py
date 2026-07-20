from __future__ import annotations

from collections.abc import Iterable


def repository_access_diagnostic(access_rows: Iterable[object], authorized_lines: list[str]) -> dict[str, int | bool]:
    """Evaluate installed repository keys against enabled devices only.

    Access rows remain stored for disabled devices so they can be restored when
    the device is enabled again. They are intentionally absent from
    authorized_keys and must therefore not turn diagnostics red.
    """
    rows = list(access_rows)
    active_rows = [row for row in rows if bool(getattr(getattr(row, "host", None), "enabled", False))]
    ready_rows = [row for row in active_rows if bool(getattr(row, "public_key", None))]
    forced_command_valid = all(
        line.startswith('restrict,command="/usr/local/bin/bbm-borg-serve --repository /repositories/')
        and " bbm-access-h" in line
        for line in authorized_lines
    )
    access_complete = (
        len(active_rows) == len(ready_rows) == len(authorized_lines)
        and forced_command_valid
    )
    return {
        "authorized_device_keys": len(authorized_lines),
        "repository_access_rows": len(active_rows),
        "repository_access_ready_rows": len(ready_rows),
        "repository_access_inactive_rows": max(0, len(rows) - len(active_rows)),
        "all_keys_use_forced_command": forced_command_valid,
        "repository_access_complete": access_complete,
    }
