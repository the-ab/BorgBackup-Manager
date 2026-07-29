from __future__ import annotations

import json
from typing import Any

# The remaining-time display is intentionally deterministic. BBM assumes a
# 1-Gbit/s source interface and uses 80% of its nominal line rate as the
# effective transfer budget. No measured network rate, Borg short-term rate,
# previous runtime or files-cache phase is fed into the estimate.
ASSUMED_INTERFACE_GBIT_PER_SECOND = 1.0
ASSUMED_LINK_UTILIZATION = 0.80
ASSUMED_TRANSFER_BYTES_PER_SECOND = int(
    ASSUMED_INTERFACE_GBIT_PER_SECOND * 1_000_000_000 / 8 * ASSUMED_LINK_UTILIZATION
)


def _safe_int(value: Any) -> int | None:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None



def parse_source_detail(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    unsupported = payload.get("unsupported_patterns")
    return {
        **payload,
        "quality": str(payload.get("quality") or "unknown"),
        "scan_method": str(payload.get("scan_method") or ""),
        "warning_count": _safe_int(payload.get("warning_count")) or 0,
        "unsupported_patterns": [
            str(value) for value in unsupported[:50]
        ] if isinstance(unsupported, list) else [],
    }


def source_stats_limitations(raw: str | None) -> list[dict[str, Any]]:
    detail = parse_source_detail(raw)
    limitations: list[dict[str, Any]] = []
    if detail.get("scan_method") == "find-stat-fallback":
        limitations.append({"code": "fallback"})
    unsupported_count = len(detail.get("unsupported_patterns") or [])
    if unsupported_count:
        limitations.append({"code": "unsupported-patterns", "count": unsupported_count})
    if detail.get("nodump_supported") is False:
        limitations.append({"code": "nodump-unavailable"})
    warning_count = _safe_int(detail.get("warning_count")) or 0
    if warning_count:
        limitations.append({"code": "read-warnings", "count": warning_count})
    if not limitations and detail.get("quality") == "partial":
        limitations.append({"code": "unspecified"})
    return limitations

def _archive_prefix(source: str) -> str:
    value = source.strip().replace("\\", "/")
    if value == "/":
        return ""
    return value.strip("/")


def source_for_archive_path(path: str, source_paths: list[str]) -> str | None:
    archive_path = str(path or "").strip().lstrip("/")
    matches: list[tuple[int, str]] = []
    root_source: str | None = None
    for source in source_paths:
        prefix = _archive_prefix(source)
        if not prefix:
            root_source = source
            continue
        if archive_path == prefix or archive_path.startswith(prefix + "/"):
            matches.append((len(prefix), source))
    if matches:
        return max(matches)[1]
    return root_source


def _remaining_file_factor(remaining_bytes: int, remaining_files: int | None) -> float:
    """Apply a small deterministic penalty for many small remaining files."""
    if not remaining_files or remaining_files <= 0 or remaining_bytes <= 0:
        return 1.0
    average = remaining_bytes / remaining_files
    gib = 1024 ** 3
    mib = 1024 ** 2
    if average >= gib:
        return 1.00
    if average >= 100 * mib:
        return 1.05
    if average >= 10 * mib:
        return 1.15
    if average >= mib:
        return 1.30
    return 1.50


def estimate_fixed_baseline_remaining(
    *,
    progress: dict[str, Any],
    source_paths: list[str],
    total_bytes: int | None,
    total_files: int | None,
    total_origin: str | None,
) -> dict[str, Any]:
    """Calculate progress and remaining time from a frozen source baseline.

    The baseline is the last known source size/file count captured for the run.
    Current Borg O/N counters are subtracted directly. Remaining bytes are then
    divided by a fixed effective 1-Gbit/s assumption (80% usable line rate).
    Remaining file count only applies a deterministic small-file penalty.
    """
    original = _safe_int(progress.get("original_bytes")) or 0
    files = _safe_int(progress.get("files")) or 0
    effective_total_bytes = _safe_int(total_bytes)
    effective_total_files = _safe_int(total_files)

    byte_baseline_exceeded = bool(
        effective_total_bytes is not None and original > effective_total_bytes
    )
    file_baseline_exceeded = bool(
        effective_total_files is not None and files > effective_total_files
    )

    remaining_bytes = None
    if effective_total_bytes is not None and not byte_baseline_exceeded:
        remaining_bytes = max(0, effective_total_bytes - original)
    remaining_files = None
    if effective_total_files is not None and not file_baseline_exceeded:
        remaining_files = max(0, effective_total_files - files)

    ratios: list[float] = []
    if effective_total_bytes and not byte_baseline_exceeded:
        ratios.append(max(0.0, min(1.0, original / effective_total_bytes)))
    if effective_total_files and not file_baseline_exceeded:
        ratios.append(max(0.0, min(1.0, files / effective_total_files)))
    progress_ratio = (sum(ratios) / len(ratios)) if ratios else None

    file_factor = 1.0
    eta_seconds = None
    if remaining_bytes is not None:
        file_factor = _remaining_file_factor(remaining_bytes, remaining_files)
        raw_seconds = remaining_bytes / ASSUMED_TRANSFER_BYTES_PER_SECOND
        eta_seconds = max(0, int(round(raw_seconds * file_factor)))

    # Current source remains useful context in the live log, but a separate
    # per-source percentage is intentionally not calculated. The global live
    # progress already exposes the meaningful percentage and duplicating a
    # source percentage created transient/redundant 0% output.
    current_source = source_for_archive_path(str(progress.get("path") or ""), source_paths)

    byte_fallback_active = bool(
        file_baseline_exceeded
        and not byte_baseline_exceeded
        and effective_total_bytes is not None
    )

    return {
        "estimated_total_bytes": effective_total_bytes,
        "estimated_total_files": effective_total_files,
        "estimated_percent": (
            None if progress_ratio is None else min(99.9, max(0.0, progress_ratio * 100.0))
        ),
        "estimated_eta_seconds": eta_seconds,
        "estimated_remaining_bytes": remaining_bytes,
        "estimated_remaining_files": remaining_files,
        "estimate_file_factor": file_factor,
        "estimate_basis": "fixed-1g-source-baseline",
        "estimate_total_origin": total_origin,
        # Remaining time is byte-based. A stale file count therefore switches
        # to a pure size fallback instead of suppressing a still-valid ETA.
        "estimate_baseline_exceeded": byte_baseline_exceeded,
        "estimate_byte_baseline_exceeded": byte_baseline_exceeded,
        "estimate_file_baseline_exceeded": file_baseline_exceeded,
        "estimate_byte_fallback_active": byte_fallback_active,
        "estimate_assumed_interface_gbps": ASSUMED_INTERFACE_GBIT_PER_SECOND,
        "estimate_assumed_utilization_percent": int(round(ASSUMED_LINK_UTILIZATION * 100)),
        "estimate_assumed_bytes_per_second": ASSUMED_TRANSFER_BYTES_PER_SECOND,
        "current_source": current_source,
    }
