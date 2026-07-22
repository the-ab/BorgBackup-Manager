#!/usr/bin/env python3
"""Static release audit for missing references and orphaned project files."""

from __future__ import annotations

import ast
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def audit_python_modules() -> None:
    modules = {path.stem: path for path in APP.glob("*.py") if path.name != "__init__.py"}
    imported: set[str] = set()
    for path in APP.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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

    # main is the Uvicorn entrypoint; the other modules are intentional
    # ``python -m`` administration entrypoints referenced by shell scripts.
    entrypoints = {"main", "account_recovery", "initial_admin", "security_bootstrap"}
    for name in sorted(set(modules) - imported - entrypoints):
        error(f"Unreferenced app module: app/{name}.py")

    corpus = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".sh", ".md", ".html"}
    )
    for entrypoint in sorted(entrypoints - {"main"}):
        if f"app.{entrypoint}" not in corpus:
            error(f"CLI module is not referenced by scripts or documentation: app/{entrypoint}.py")


def audit_static_files(version: str) -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
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

    version_markers = re.findall(r"/static/[^'\"`?]+\?v=([0-9.]+)", index + "\n" + app_js)
    stale = sorted({marker for marker in version_markers if marker != version})
    if stale:
        error(f"Stale static asset version marker(s): {', '.join(stale)}; expected {version}")




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
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    backend = (APP / "main.py").read_text(encoding="utf-8")
    routes = {
        match.group(1).removeprefix("/api")
        for match in re.finditer(
            r'@app\.(?:get|post|put|delete|patch)\("([^"]+)"', backend
        )
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
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
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
        text = path.read_text(encoding="utf-8", errors="replace")
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
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    audit_python_modules()
    audit_static_files(version)
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
