from pathlib import Path
import re

from app.main import app


def test_release_version_matches_api_version():
    project_root = Path(__file__).parents[1]
    release_version = (project_root / "VERSION").read_text(encoding="utf-8").strip()

    assert release_version
    assert app.version == release_version
    assert "COPY VERSION ./VERSION" in (project_root / "Dockerfile").read_text(encoding="utf-8")


def test_embedded_python_in_update_script_compiles():
    project_root = Path(__file__).parents[1]
    script = (project_root / "update.sh").read_text(encoding="utf-8")
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", script, flags=re.DOTALL)

    assert blocks
    for index, source in enumerate(blocks):
        compile(source, f"update.sh heredoc {index}", "exec")
