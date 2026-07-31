#!/usr/bin/env python3
"""Static release audit for version drift, dead references and orphaned project content."""

from __future__ import annotations

import ast
import re
import shlex
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def audit_version_consistency(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        error(f"Invalid root VERSION: {version!r}")
    if (APP / "VERSION").exists():
        error("Redundant app/VERSION present; root VERSION is the single authoritative version file")

    expected = {
        ROOT / "README.md": f"# BorgBackup Manager {version}",
        ROOT / "README.de.md": f"# BorgBackup Manager {version}",
        ROOT / "INSTALLATION.md": f"# Installation and Operations — BorgBackup Manager {version}",
        ROOT / "INSTALLATION.de.md": f"# Installation und Betrieb – BorgBackup Manager {version}",
    }
    for path, first_line in expected.items():
        if not path.is_file():
            error(f"Missing versioned document: {path.name}")
            continue
        actual = _read(path).splitlines()[0] if _read(path).splitlines() else ""
        if actual != first_line:
            error(f"Stale document title in {path.name}: {actual!r}; expected {first_line!r}")

    doc_markers = {
        ROOT / "README.md": f"BorgBackup-Manager-{version}.zip",
        ROOT / "README.de.md": f"BorgBackup-Manager-{version}.zip",
        ROOT / "INSTALLATION.md": f"BorgBackup-Manager-{version}.zip",
        ROOT / "INSTALLATION.de.md": f"BorgBackup-Manager-{version}.zip",
        STATIC / "help.en.html": f"version {version}",
        STATIC / "help.de.html": f"Version {version}",
    }
    for path, marker in doc_markers.items():
        if not path.is_file() or marker not in _read(path):
            error(f"Current-version marker missing in {path.relative_to(ROOT)}: {marker}")

    index = _read(STATIC / "index.html")
    app_js = _read(STATIC / "app.js")
    if f"v{version}</b>" not in index:
        error(f"Login version marker is stale; expected v{version}")
    markers = re.findall(r"/static/[^'\"`?]+\?v=([0-9.]+)", index + "\n" + app_js)
    stale = sorted({marker for marker in markers if marker != version})
    if stale:
        error(f"Stale static asset version marker(s): {', '.join(stale)}; expected {version}")

    release_en = _read(ROOT / "RELEASE_NOTES.md")
    release_de = _read(ROOT / "RELEASE_NOTES.de.md")
    if f"## v{version} " not in release_en.split("\n", 12)[0:12]:
        # The list check above is intentionally strict about the first release block.
        if not release_en.startswith(f"# Release Notes\n\n## v{version} "):
            error(f"RELEASE_NOTES.md does not start with v{version}")
    if not release_de.startswith(f"# Release Notes\n\n## v{version} "):
        error(f"RELEASE_NOTES.de.md does not start with v{version}")


def audit_document_feature_alignment() -> None:
    en = _read(ROOT / "INSTALLATION.md")
    de = _read(ROOT / "INSTALLATION.de.md")
    required = (
        (en, "Reload from Repository", "INSTALLATION.md missing current archive background-scan wording"),
        (en, "background run", "INSTALLATION.md missing asynchronous archive-scan description"),
        (en, "`--list --filter AMCE`", "INSTALLATION.md missing current AMCE live-counter behavior"),
        (en, "1-Gbit/s", "INSTALLATION.md missing current 1-Gbit/s remaining-time model"),
        (en, "Manage Borg cache", "INSTALLATION.md missing current Borg-cache management scope"),
        (de, "Neu aus Repository einlesen", "INSTALLATION.de.md missing current archive background-scan wording"),
        (de, "Hintergrund-Ausführung", "INSTALLATION.de.md missing asynchronous archive-scan description"),
        (de, "`--list --filter AMCE`", "INSTALLATION.de.md missing current AMCE live-counter behavior"),
        (de, "1-Gbit/s", "INSTALLATION.de.md missing current 1-Gbit/s remaining-time model"),
        (de, "Borg-Cache verwalten", "INSTALLATION.de.md missing current Borg-cache management scope"),
    )
    for text, marker, message in required:
        if marker not in text:
            error(message)
    forbidden = (
        "Beim ersten Zugriff oder nach einer erfolgreichen Archivänderung liest der Manager Borg neu ein",
        "Der Client-Scan prüft ausschließlich `$HOME/.cache/borgbackup-manager/`",
        "Neue 0.9.x-Backups enthalten Sicherheitsdatenbank",
        "--list --filter CE",
        "Live scan before exclusions",
        "backup-run limit per repository",
        "Maximal parallele Backup-Läufe",
        "Der begrenzte Borg-Progress-Verlauf",
        "The bounded Borg progress history",
    )
    for marker in forbidden:
        if marker in en or marker in de:
            error(f"Outdated documentation wording still present: {marker}")


def audit_current_source_stats_and_parallelism() -> None:
    runner = _read(APP / "runner.py")
    service = _read(APP / "service.py")
    models = _read(APP / "models.py")
    schemas = _read(APP / "schemas.py")
    index = _read(STATIC / "index.html")
    app_js = _read(STATIC / "app.js")
    progress = _read(APP / "borg_progress.py")

    pattern_check = runner.find("if excluded_by_pattern(path):")
    stat_call = runner.find("item_stat = entry.stat(follow_symlinks=False)")
    if pattern_check < 0 or stat_call < 0 or pattern_check > stat_call:
        error("Source-stat path exclusions are not checked before entry.stat()")
    if '"path_excluded_count": path_excluded_count' not in runner:
        error("Source-stat scanner does not report pre-stat path exclusions")

    obsolete_parallel_markers = {
        "service.py": "_repository_parallel_limit",
        "models.py": "parallel_limit: Mapped[int] = mapped_column(Integer, default=1)",
        "index.html": "Maximal parallele Backup-Läufe",
        "app.js": "repo.parallel_limit",
    }
    texts = {"service.py": service, "models.py": models, "schemas.py": schemas, "index.html": index, "app.js": app_js}
    for name, obsolete in obsolete_parallel_markers.items():
        if obsolete in texts[name]:
            error(f"Obsolete configurable repository parallelism remains in {name}: {obsolete}")

    repository_schema_classes = ("RepositoryIn", "RepositoryImportIn", "RepositoryUpdate", "RepositoryOut")
    for index_no, class_name in enumerate(repository_schema_classes):
        start = schemas.find(f"class {class_name}")
        if start < 0:
            error(f"Repository schema class missing: {class_name}")
            continue
        later_starts = [
            schemas.find(f"class {other}", start + 1)
            for other in repository_schema_classes[index_no + 1:]
        ]
        later_starts.extend([
            match.start()
            for match in re.finditer(r"^class \w+", schemas[start + 1:], re.MULTILINE)
        ])
        later_starts = [value if value >= start else start + 1 + value for value in later_starts if value >= 0]
        end = min(later_starts) if later_starts else len(schemas)
        block = schemas[start:end]
        if re.search(r"^\s+parallel_limit\s*:", block, re.MULTILINE):
            error(f"Obsolete repository parallel_limit remains in schema class {class_name}")
    if 'return _capacity_semaphore(_repository_locks, (id(loop), f"repository-id:{repository_id}"), 1)' not in service:
        error("Repository runtime lock is not scoped to one repository record")
    if "mount_parallel_limits" not in schemas or "mount_parallel_limits" not in app_js:
        error("Mount-level parallelism controls are missing")
    if "external_storage_parallel_limits" not in schemas or "external_storage_parallel_limits" not in app_js:
        error("External-filesystem parallelism controls are missing")
    main_source = _read(APP / "main.py")
    if "external_filesystem_parallel_identity" not in service or "external_filesystem_parallel_identity" not in main_source:
        error("External repositories are not grouped by detected remote filesystem")
    if "class _AdjustableCapacity" not in service or "async def _acquire_mount_capacity" not in service:
        error("Live-resizable mount capacity limiter is missing")
    if "await asyncio.wait_for(limiter.acquire(), timeout=0.25)" not in service:
        error("Interactive mount capacity does not refresh changed limits")
    inner_start = service.find("async def _execute_run_inner")
    inner_end = service.find("async def execute_run", inner_start)
    inner_block = service[inner_start:inner_end] if inner_start >= 0 and inner_end > inner_start else ""
    if "await _acquire_mount_capacity" in inner_block:
        error("Persisted runs still reserve a second process-local mount slot before queue admission")
    if "single admission controller" not in inner_block:
        error("Persisted queue does not document the single admission-controller invariant")
    if "tuple[int, asyncio.Semaphore]" in service:
        error("Obsolete non-resizable semaphore cache remains")

    main = _read(APP / "main.py")
    storage_guard = _read(APP / "storage_guard.py")
    if '"global_parallel_limit": int(settings.max_parallel_runs or 0)' not in main:
        error("System diagnostics do not expose the global parallel limit")
    if '"parallel_limit": int((getattr(settings, "mount_parallel_limits", {}) or {}).get(str(mount), 0))' not in storage_guard:
        error("Repository filesystem diagnostics do not expose effective mount limits")
    if "wirksame Grenze für verschiedene Repositorys dieses Dateisystems" not in app_js:
        error("Repository filesystem diagnostics do not render mount parallelism")
    if "running_runs" not in main or "queued_runs" not in main or "aktiv ${Number(item.running_runs" not in app_js:
        error("Repository filesystem diagnostics do not expose current mount queue occupancy")

    for obsolete in ("Qualität hoch", "aus letztem Borg-Lauf beobachtet", "source_stats_by_path", "source_stats_quality"):
        if obsolete in app_js:
            error(f"Obsolete normal source-stat detail remains in app.js: {obsolete}")
    if "source_stats_limitations" not in app_js or "sourceStatsLimitationText" not in app_js:
        error("Concrete source-stat limitation rendering is missing")

    for obsolete in ("_live_progress_history", "get_run_progress_history", "deque(maxlen=720)"):
        if obsolete in progress or obsolete in service:
            error(f"Obsolete Borg progress-history logic remains: {obsolete}")



def audit_eta_fallback_search_and_modal_editing() -> None:
    eta = _read(APP / "backup_eta.py")
    app_js = _read(STATIC / "app.js")
    index = _read(STATIC / "index.html")
    css = _read(STATIC / "style.css")

    required_eta = (
        '"estimate_baseline_exceeded": byte_baseline_exceeded',
        '"estimate_byte_fallback_active": byte_fallback_active',
        'byte_fallback_active = bool(',
    )
    for marker in required_eta:
        if marker not in eta:
            error(f"Size-based ETA fallback marker missing: {marker}")
    if '"estimate_baseline_exceeded": byte_baseline_exceeded or file_baseline_exceeded' in eta:
        error("File-count overflow still suppresses the byte-based ETA")

    for marker in ('id="repo-search"', 'id="host-search"', 'id="entity-edit-dialog"'):
        if marker not in index:
            error(f"Search/modal UI marker missing: {marker}")
    for marker in (
        "state.repositorySearch", "state.hostSearch", "function openEntityEditDialog",
        "function closeEntityEditDialog", "entity-edit-form-placeholder",
    ):
        if marker not in app_js and marker not in css:
            error(f"Search/modal implementation marker missing: {marker}")
    if "body.entity-edit-dialog-open" not in css:
        error("Modal editor does not lock background scrolling")

    edit_blocks = (
        ("editHost", "resetHostSshActionForm"),
        ("editRepository", "prepareRepositoryImport"),
        ("editJob", "bindForm"),
    )
    for function_name, next_name in edit_blocks:
        if f"function {function_name}" not in app_js or f"function {next_name}" not in app_js:
            error(f"Modal edit function boundary missing: {function_name}")
            continue
        block = app_js.split(f"function {function_name}", 1)[1].split(f"function {next_name}", 1)[0]
        if "openEntityEditDialog" not in block:
            error(f"{function_name} does not open the modal editor")
        if "scrollIntoView" in block:
            error(f"{function_name} still scrolls the page to the form")


def audit_archive_scan_locking_and_checkpoint_ui() -> None:
    service = _read(APP / "service.py")
    index = _read(STATIC / "index.html")
    app_js = _read(STATIC / "app.js")

    start = service.find("async def execute_interactive")
    end = service.find("EXTERNAL_STORAGE_POLL_SECONDS", start)
    block = service[start:end] if start >= 0 and end > start else ""
    if not block:
        error("Interactive repository execution helper is missing")
    elif "if mount_lock and mount_acquired:" not in block or "mount_lock.release()" not in block:
        error("Interactive repository commands do not release acquired mount capacity")

    if 'id="archive-consider-checkpoints"' in index:
        error("Redundant checkpoint toggle remains in the normal archive overview")
    if 'name="consider_checkpoints"' not in index:
        error("Restore checkpoint opt-in is missing")
    load_start = app_js.find("async function loadArchives(options = {})")
    load_end = app_js.find("function archiveSelectionDeviceLabel", load_start)
    load_block = app_js[load_start:load_end] if load_start >= 0 and load_end > load_start else ""
    if "archive-consider-checkpoints" in load_block or "bbm-archive-checkpoints" in load_block:
        error("Normal archive refresh still depends on the removed checkpoint toggle")
    if "const checkpointInfo = checkpoints ?" not in app_js:
        error("Normal archive overview does not report automatically detected checkpoints")

def audit_archive_delete_queueing() -> None:
    main = _read(APP / "main.py")
    app_js = _read(STATIC / "app.js")
    start = main.find('@app.post("/api/repositories/{repository_id}/archive-delete"')
    end = main.find('@app.get("/api/jobs/{job_id}/archives"', start)
    block = main[start:end] if start >= 0 and end > start else ""
    if not block:
        error("Repository archive-delete endpoint is missing")
        return
    for forbidden in ("execute_interactive(", "repository_list_command(", "parse_archive_listing("):
        if forbidden in block:
            error(f"Archive deletion still scans Borg synchronously before queueing: {forbidden}")
    if "load_archive_cache(repository_id" not in block or "queue_repository_action(" not in block:
        error("Archive deletion does not use cached metadata and immediate queueing")

    js_start = app_js.find("async function deleteArchives(repositoryId, archives)")
    js_end = app_js.find("async function deleteArchive", js_start + 1)
    js_block = app_js[js_start:js_end] if js_start >= 0 and js_end > js_start else ""
    if not js_block:
        error("Archive deletion frontend handler is missing")
    elif js_block.find("showRun(result.run_id)") > js_block.find("await refreshAreas(['dashboard', 'runs']"):
        error("Archive deletion does not open the queued run before secondary view refreshes")


def audit_python_modules() -> None:
    modules = {path.stem: path for path in APP.glob("*.py") if path.name != "__init__.py"}
    imported: set[str] = set()
    for path in APP.glob("*.py"):
        try:
            tree = ast.parse(_read(path), filename=str(path))
        except SyntaxError as exc:
            error(f"Python syntax error in {path.relative_to(ROOT)}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app."):
                        imported.add(alias.name.split(".", 2)[1])
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                imported.add(node.module.split(".", 2)[1])

    entrypoints = {"main", "account_recovery", "initial_admin", "security_bootstrap"}
    for name in sorted(set(modules) - imported - entrypoints):
        error(f"Unreferenced app module: app/{name}.py")

    corpus = "\n".join(
        _read(path)
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".sh", ".md", ".html"}
    )
    for entrypoint in sorted(entrypoints - {"main"}):
        if f"app.{entrypoint}" not in corpus:
            error(f"CLI module is not referenced by scripts or documentation: app/{entrypoint}.py")


def audit_unused_python_imports() -> None:
    for path in sorted(APP.glob("*.py")):
        try:
            tree = ast.parse(_read(path), filename=str(path))
        except SyntaxError:
            continue
        loaded = Counter(
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        )
        for node in tree.body:
            if isinstance(node, ast.Import):
                aliases = [(alias.asname or alias.name.split(".", 1)[0], alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue
                aliases = [(alias.asname or alias.name, f"{node.module}.{alias.name}") for alias in node.names if alias.name != "*"]
            else:
                continue
            for local_name, origin in aliases:
                if loaded[local_name] == 0:
                    error(f"Unused Python import in {path.relative_to(ROOT)}:{node.lineno}: {origin} as {local_name}")


def audit_dead_top_level_definitions() -> None:
    sources = {path: _read(path) for path in APP.glob("*.py")}
    corpus = "\n".join(sources.values()) + "\n" + "\n".join(_read(path) for path in (ROOT / "tests").glob("*.py"))
    for path, source in sorted(sources.items()):
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            if len(re.findall(rf"\b{re.escape(name)}\b", corpus)) > 1:
                continue
            # FastAPI middleware/routes are registered by decorators; the function
            # name itself does not need a second textual reference.
            if path.name == "main.py" and node.decorator_list:
                continue
            error(f"Unreferenced top-level definition: {path.relative_to(ROOT)}:{node.lineno} {name}")


def audit_static_files() -> None:
    index = _read(STATIC / "index.html")
    referenced = {
        Path(value.split("?", 1)[0]).name
        for value in re.findall(r'(?:src|href)="([^"]+)"', index)
        if value.startswith("/static/")
    }
    referenced.update({"index.html", "help.de.html", "help.en.html"})
    existing = {path.name for path in STATIC.iterdir() if path.is_file()}
    for name in sorted(referenced - existing):
        error(f"Missing static asset: app/static/{name}")
    for name in sorted(existing - referenced):
        error(f"Unreferenced static asset: app/static/{name}")


def audit_css_references() -> None:
    css = _read(STATIC / "style.css")
    corpus = "\n".join(
        _read(STATIC / name)
        for name in ("index.html", "app.js", "i18n.js", "help.de.html", "help.en.html")
    )
    classes = sorted(set(re.findall(r"(?<![\w-])\.([A-Za-z_][\w-]*)", css)))
    for class_name in classes:
        if re.search(rf"(?<![\w-]){re.escape(class_name)}(?![\w-])", corpus) is None:
            error(f"Unreferenced CSS class selector: .{class_name}")

    # Guard the shared action-button foundation. A cleanup must not remove the
    # base rule merely because action buttons are generated dynamically.
    required_button_markers = (
        "--button-radius:",
        "--button-shadow:",
        "Shared action-button system",
        "button:where(:not(.link):not(.entity-link):not(.metric):not(.section-link):not(.system-tab):not(.sync-state):not(.inline-action):not(nav button))",
        "button.secondary:not(:disabled):hover",
        "button.danger.ghost:not(:disabled):hover",
    )
    for marker in required_button_markers:
        if marker not in css:
            error(f"Shared action-button style marker missing: {marker}")


def audit_i18n() -> None:
    text = _read(STATIC / "i18n.js")
    match = re.search(r"const exact = \{(.*?)\n  \};\n\n  const patterns", text, re.S)
    if not match:
        error("Could not locate i18n exact translation dictionary")
        return
    keys = re.findall(r'^\s*"((?:\\.|[^"])*)"\s*:', match.group(1), re.M)
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        error("Duplicate i18n exact key(s): " + ", ".join(duplicates))
    required = {
        "Repository-Scan wird eingereiht …",
        "Archiv-Zwischenspeicher wird geladen …",
        "Archivliste wird aus dem Zwischenspeicher geladen …",
        "Noch keine gespeicherte Archivliste vorhanden.",
        "„Neu aus Repository einlesen“ startet den Repository-Scan als Hintergrund-Ausführung. Auch große Repositorys bleiben dadurch unabhängig vom HTTP-Timeout.",
        "Aktualisierung fehlgeschlagen – vorherige Liste bleibt sichtbar.",
    }
    missing = sorted(required - set(keys))
    if missing:
        error("Missing current archive i18n key(s): " + ", ".join(missing))
    for marker in ("Repository wird als Ausführung #", "Archivscan #"):
        if marker not in text:
            error(f"Missing current dynamic archive translation pattern: {marker}")
    for obsolete in ("Archivliste wird manuell aktualisiert …", "Repository wird eingelesen …"):
        if obsolete in set(keys):
            error(f"Obsolete i18n key still present: {obsolete}")


def _route_regex(path: str) -> re.Pattern[str]:
    parts: list[str] = []
    position = 0
    for match in re.finditer(r"(\$\{[^}]+\}|\{[^}]+\})", path):
        parts.append(re.escape(path[position:match.start()]))
        parts.append(r"[^/]+")
        position = match.end()
    parts.append(re.escape(path[position:]))
    return re.compile("^" + "".join(parts) + "$")


def audit_debug_error_boundary() -> None:
    debug_logging = _read(APP / "debug_logging.py")
    main = _read(APP / "main.py")
    service = _read(APP / "service.py")
    notifications = _read(APP / "notifications.py")
    javascript = _read(STATIC / "app.js")
    stylesheet = _read(STATIC / "style.css")

    required_debug = (
        "def detail_requires_debug_log",
        "def log_unexpected_exception",
        "def public_error_message",
        "class _IncidentOnlyFilter",
        "source-statistics output is deliberately not treated as an incident",
        "Technical detail:",
    )
    for required in required_debug:
        if required not in debug_logging:
            error(f"Central debug error boundary is incomplete: {required}")
    if "@app.exception_handler(StarletteHTTPException)" not in main:
        error("Technical HTTPException details are not centrally sanitized")
    if '"Unhandled HTTP exception"' not in main or "public_error_message(error_id)" not in main:
        error("Unhandled HTTP exceptions do not return a short debug-log reference")
    if "Existing repository import failed unexpectedly" not in main:
        error("Unexpected repository-import failures are not written to debug.log")
    for marker in (
        "Execution #{run_id} failed unexpectedly",
        "Archive scan execution #{run_id} failed unexpectedly",
        "Repository initialization finalization",
        "_background_error_message",
    ):
        if marker not in service:
            error(f"Background traceback logging is incomplete: {marker}")
    if 'LOGGER.exception("Notification delivery failed' not in notifications:
        error("Notification delivery tracebacks are not written to debug.log")
    if "function browserSafeErrorMessage(value)" not in javascript:
        error("Frontend traceback fallback is missing")
    if "if (!bad) toastTimer = setTimeout(hideToast, 3200);" not in javascript:
        error("Normal success-toast timeout is missing")
    if "else if (Number(autoHideMs) > 0) toastTimer = setTimeout(hideToast, Number(autoHideMs));" not in javascript:
        error("Optional timed error-toast handling is missing")
    if "toast(`Ausführung #${runId} ${label}`, !good, good ? null : 6000);" not in javascript:
        error("Short failed-run notification does not disappear after six seconds")
    if "text.length > 1200" in javascript or "_TECHNICAL_DETAIL_LIMIT" in debug_logging:
        error("Long normal output is still misclassified as a debug incident")
    if "response.status_code >= 500" not in main or "HTTP {exc.status_code} response was recorded" not in main:
        error("Application-side HTTP 5xx responses are not recorded in debug.log")
    if "close.onclick = hideToast" not in javascript:
        error("Dismissible error toasts cannot be closed")
    if "#toast.show { opacity: 1; transform: translateY(0); pointer-events: auto; }" not in stylesheet:
        error("Persistent error toast interaction styling is missing")
    if "bad ? 8000" in javascript:
        error("Obsolete generic timed error-toast behavior remains")
    document_markers = {
        ROOT / "README.md": "`/data/logs/debug.log` is restricted to real incidents",
        ROOT / "README.de.md": "`/data/logs/debug.log` ist ausschließlich für echte Störfälle vorgesehen",
        ROOT / "INSTALLATION.md": "The incident log `/data/logs/debug.log` stores unexpected tracebacks",
        ROOT / "INSTALLATION.de.md": "Das Störungsprotokoll `/data/logs/debug.log` speichert unerwartete Tracebacks",
        STATIC / "help.en.html": "The debug log is restricted to unexpected tracebacks",
        STATIC / "help.de.html": "Das Debug-Log ist auf unerwartete Tracebacks",
    }
    for path, marker in document_markers.items():
        if marker not in _read(path):
            error(f"Debug error-boundary documentation missing in {path.relative_to(ROOT)}")


def audit_frontend_api_routes() -> None:
    javascript = _read(STATIC / "app.js")
    backend = _read(APP / "main.py")
    routes = {
        match.group(1).removeprefix("/api")
        for match in re.finditer(r'@app\.(?:get|post|put|delete|patch)\("([^"]+)"', backend)
    }
    direct_refs = {
        match.group(2).split("?", 1)[0]
        for match in re.finditer(r"\bapi\(\s*([`'\"])(/[^`'\"]+)\1", javascript)
    }
    for reference in sorted(direct_refs):
        if reference == "/${type}/${id}":
            for prefix in ("/hosts/", "/repositories/", "/jobs/"):
                if not any(route.startswith(prefix + "{") for route in routes):
                    error(f"Generic frontend delete route lacks backend endpoint for {prefix}")
            continue
        if reference.endswith("/") and any(route.startswith(reference + "{") for route in routes):
            continue
        if not any(_route_regex(route).match(reference) for route in routes):
            error(f"Frontend API reference has no backend route: {reference}")


def audit_docker_sources() -> None:
    dockerfile = _read(ROOT / "Dockerfile")
    for raw_line in dockerfile.splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            error(f"Invalid Docker COPY line: {line}: {exc}")
            continue
        sources = [part for part in parts[1:-1] if not part.startswith("--")]
        for source in sources:
            if any(token in source for token in "*?["):
                continue
            if not (ROOT / source.rstrip("/")).exists():
                error(f"Docker COPY source does not exist: {source}")


def audit_markdown_links() -> None:
    for path in ROOT.glob("*.md"):
        text = _read(path)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = target.strip().split("#", 1)[0]
            if not target or re.match(r"^(?:https?://|mailto:)", target):
                continue
            candidate = (path.parent / target).resolve()
            try:
                candidate.relative_to(ROOT.resolve())
            except ValueError:
                error(f"Markdown link escapes project root in {path.name}: {target}")
                continue
            if not candidate.exists():
                error(f"Broken local Markdown link in {path.name}: {target}")


def audit_release_layout() -> None:
    for runtime_directory in ("data", "repositories"):
        if (ROOT / runtime_directory).exists():
            error(f"Runtime directory must not be included: {runtime_directory}/")
    if (ROOT / ".github").exists():
        error(".github must not be included; releases are published manually")
    legacy = ROOT / "RELEASE_NOTES.en.md"
    if legacy.exists():
        error(f"Legacy release-notes file present: {legacy.name}")
    pairs = (
        (ROOT / "RELEASE_NOTES.md", APP / "RELEASE_NOTES.md"),
        (ROOT / "RELEASE_NOTES.de.md", APP / "RELEASE_NOTES.de.md"),
    )
    for source, compatibility_copy in pairs:
        if not source.is_file():
            error(f"Missing release notes: {source.name}")
            continue
        if not compatibility_copy.is_file():
            error(f"Missing old-updater compatibility copy: {compatibility_copy.relative_to(ROOT)}")
        elif source.read_bytes() != compatibility_copy.read_bytes():
            error(f"Release-note compatibility copy differs: {compatibility_copy.relative_to(ROOT)}")



def audit_standalone_image_deployment(version: str) -> None:
    compose_path = ROOT / "docker-compose" / "compose.yaml"
    env_path = ROOT / "docker-compose" / ".env.example"
    readme_de_path = ROOT / "docker-compose" / "README.de.md"
    readme_en_path = ROOT / "docker-compose" / "README.md"
    if not all(path.is_file() for path in (compose_path, env_path, readme_de_path, readme_en_path)):
        error("Standalone docker-compose bundle is incomplete")
        return
    compose = _read(compose_path)
    sample = _read(env_path)
    readme_de = _read(readme_de_path)
    readme_en = _read(readme_en_path)
    entrypoint = _read(ROOT / "docker" / "entrypoint.sh")
    required = (
        "image: ghcr.io/the-ab/borgbackup-manager:${BBM_IMAGE_TAG:-latest}",
        "${BBM_REPOSITORY_PATH:-/docker_data/borgbackup-manager/repositories}:/repositories:rslave",
        "./.env:/run/bbm-host.env",
    )
    for marker in required:
        if marker not in compose:
            error(f"Standalone compose marker missing: {marker}")
    if "build:" in compose:
        error("Standalone GHCR compose must not contain a local build")
    if "BBM_IMAGE_TAG=latest" not in sample or f"v{version}" not in sample:
        error("Standalone .env example does not document latest and the current fixed tag")
    if "BBM_DEBUG_LOG_LEVEL" in sample or "BBM_DEBUG_LOG_LEVEL" in _read(ROOT / ".env.example"):
        error("Obsolete BBM_DEBUG_LOG_LEVEL remains in an example configuration")
    for variable in ("BBM_REPOSITORY_PUBLIC_HOST", "BBM_DATA_PATH", "BBM_REPOSITORY_PATH", "BBM_BORG_UID", "BBM_BORG_GID"):
        if variable not in readme_de or variable not in readme_en:
            error(f"Standalone .env reference does not document {variable}")
    if f"v{version}" not in readme_de or f"v{version}" not in readme_en:
        error("Standalone .env references do not document the current fixed image tag")
    if 'chown "${borg_uid}:${borg_gid}" /repositories' not in entrypoint:
        error("Entrypoint does not initialize an empty repository mount root")
    if "chown -R borg:borg /repositories" in entrypoint:
        error("Entrypoint must never recursively re-own repository contents")


def main() -> int:
    version = _read(ROOT / "VERSION").strip()
    audit_version_consistency(version)
    audit_standalone_image_deployment(version)
    audit_document_feature_alignment()
    audit_current_source_stats_and_parallelism()
    audit_eta_fallback_search_and_modal_editing()
    audit_archive_scan_locking_and_checkpoint_ui()
    audit_archive_delete_queueing()
    audit_python_modules()
    audit_unused_python_imports()
    audit_dead_top_level_definitions()
    audit_static_files()
    audit_css_references()
    audit_i18n()
    audit_debug_error_boundary()
    audit_frontend_api_routes()
    audit_docker_sources()
    audit_markdown_links()
    audit_release_layout()
    if ERRORS:
        print("Project audit failed:", file=sys.stderr)
        for item in ERRORS:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("Project reference and orphan-file audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
