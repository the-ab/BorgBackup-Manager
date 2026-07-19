from __future__ import annotations

import re
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


def test_window_exports_reference_defined_frontend_symbols() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"Object\.assign\(window,\s*\{(?P<body>.*?)\}\s*\);", source, re.DOTALL)
    assert match, "Object.assign(window, {...}) export block is missing"

    exported = {
        name
        for name in re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]*\b", match.group("body"))
        if name not in {"window"}
    }
    declared = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", source))
    declared.update(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", source))

    missing = sorted(exported - declared)
    assert not missing, f"Undefined frontend exports: {', '.join(missing)}"


def test_removed_bootstrap_host_is_not_referenced() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "bootstrapHost" not in source


def test_csp_safe_dynamic_actions_are_delegated_and_whitelisted() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    html = (APP_JS.parent / "index.html").read_text(encoding="utf-8")

    assert "onclick=\"" not in source
    assert "onclick=\"" not in html
    assert "function bbmAction(name, ...args)" in source
    assert "closest('[data-bbm-action]')" in source
    assert "const BBM_ACTION_HANDLERS = Object.freeze" in source
    assert "script-src 'self'" in (APP_JS.parents[1] / "main.py").read_text(encoding="utf-8")
    assert "'unsafe-inline'" not in (APP_JS.parents[1] / "main.py").read_text(encoding="utf-8").split("script-src", 1)[1].split(";", 1)[0]

    used = set(re.findall(r"bbmAction\('([A-Za-z_$][A-Za-z0-9_$]*)'", source))
    handlers_match = re.search(
        r"const BBM_ACTION_HANDLERS = Object\.freeze\(\{(?P<body>.*?)\}\);",
        source,
        re.DOTALL,
    )
    assert handlers_match, "BBM action whitelist is missing"
    handlers = set(re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]*\b", handlers_match.group("body")))
    assert used <= handlers, f"Unregistered delegated actions: {sorted(used - handlers)}"
