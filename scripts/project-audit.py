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
    )
    for marker in forbidden:
        if marker in en or marker in de:
            error(f"Outdated documentation wording still present: {marker}")


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


def main() -> int:
    version = _read(ROOT / "VERSION").strip()
    audit_version_consistency(version)
    audit_document_feature_alignment()
    audit_python_modules()
    audit_unused_python_imports()
    audit_dead_top_level_definitions()
    audit_static_files()
    audit_css_references()
    audit_i18n()
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
