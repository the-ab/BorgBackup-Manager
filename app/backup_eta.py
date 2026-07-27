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
    sources = payload.get("sources")
    if not isinstance(sources, list):
        sources = []
    normalized: list[dict[str, Any]] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        size = _safe_int(item.get("size_bytes"))
        files = _safe_int(item.get("file_count"))
        if not path or size is None or files is None:
            continue
        normalized.append({"path": path, "size_bytes": size, "file_count": files})
    return {
        **payload,
        "sources": normalized,
        "quality": str(payload.get("quality") or "unknown"),
    }


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


def _source_progress(history: list[dict], source_paths: list[str]) -> dict[str, dict[str, int]]:
    result = {
        path: {"original_bytes": 0, "files": 0, "deduplicated_bytes": 0}
        for path in source_paths
    }
    previous = {"original_bytes": 0, "files": 0, "deduplicated_bytes": 0}
    previous_source: str | None = None
    for item in history:
        current_source = source_for_archive_path(str(item.get("path") or ""), source_paths)
        current = {
            "original_bytes": _safe_int(item.get("original_bytes")) or 0,
            "files": _safe_int(item.get("files")) or 0,
            "deduplicated_bytes": _safe_int(item.get("deduplicated_bytes")) or 0,
        }
        # The first frame after a source transition still contains the previous
        # source's cumulative tail. Attribute that transition delta to the old
        # source; following deltas belong to the new source.
        source = previous_source if previous_source and current_source != previous_source else current_source
        if source in result:
            for key in current:
                result[source][key] += max(0, current[key] - previous[key])
        previous = current
        if current_source is not None:
            previous_source = current_source
    return result


def observed_source_statistics(
    history: list[dict[str, Any]],
    source_paths: list[str],
    *,
    final_total_bytes: int | None,
    final_total_files: int | None,
) -> dict[str, Any]:
    """Build a post-exclusion per-source distribution from Borg's finished run.

    Progress frames are sampled rather than emitted for every file. The final
    Borg totals scale the observed source shares so their sum matches the exact
    archive statistics. This remains useful for source-by-source progress and
    the next run's frozen source baseline; it is independent of ETA rates.
    """
    if not history or not source_paths:
        return {}
    observed = _source_progress(history, source_paths)
    attributed_bytes = sum(item["original_bytes"] for item in observed.values())
    attributed_files = sum(item["files"] for item in observed.values())
    latest_bytes = _safe_int(history[-1].get("original_bytes")) or 0
    latest_files = _safe_int(history[-1].get("files")) or 0
    byte_coverage = (attributed_bytes / latest_bytes) if latest_bytes > 0 else 0.0
    file_coverage = (attributed_files / latest_files) if latest_files > 0 else 0.0
    if max(byte_coverage, file_coverage) < 0.70:
        return {}
    byte_scale = (
        float(final_total_bytes) / attributed_bytes
        if final_total_bytes and attributed_bytes > 0
        else 1.0
    )
    file_scale = (
        float(final_total_files) / attributed_files
        if final_total_files and attributed_files > 0
        else 1.0
    )
    sources = []
    for path in source_paths:
        values = observed.get(path) or {}
        sources.append({
            "path": path,
            "size_bytes": max(0, int(round((values.get("original_bytes") or 0) * byte_scale))),
            "file_count": max(0, int(round((values.get("files") or 0) * file_scale))),
        })
    return {
        "version": 1,
        "quality": "observed",
        "scan_method": "borg-progress-observed",
        "sources": sources,
        "coverage": min(1.0, max(0.0, min(byte_coverage or 1.0, file_coverage or 1.0))),
    }


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
    history: list[dict[str, Any]],
    source_paths: list[str],
    source_detail_json: str | None,
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
        "estimate_baseline_exceeded": byte_baseline_exceeded or file_baseline_exceeded,
        "estimate_byte_baseline_exceeded": byte_baseline_exceeded,
        "estimate_file_baseline_exceeded": file_baseline_exceeded,
        "estimate_assumed_interface_gbps": ASSUMED_INTERFACE_GBIT_PER_SECOND,
        "estimate_assumed_utilization_percent": int(round(ASSUMED_LINK_UTILIZATION * 100)),
        "estimate_assumed_bytes_per_second": ASSUMED_TRANSFER_BYTES_PER_SECOND,
        "current_source": current_source,
    }
