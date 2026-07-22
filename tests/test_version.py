from pathlib import Path
import re

from app.main import app
from app.release import APP_RELEASE_DATE


def test_release_version_matches_api_version():
    project_root = Path(__file__).parents[1]
    release_version = (project_root / "VERSION").read_text(encoding="utf-8").strip()

    assert release_version
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", APP_RELEASE_DATE)
    assert app.version == release_version
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY VERSION ./" in dockerfile
    assert "RELEASE_DATE" not in dockerfile
    assert '"release_date": APP_RELEASE_DATE' in (project_root / "app/main.py").read_text(encoding="utf-8")
    assert not (project_root / "RELEASE_DATE").exists()


def test_embedded_python_in_update_script_compiles():
    project_root = Path(__file__).parents[1]
    script = (project_root / "update.sh").read_text(encoding="utf-8")
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", script, flags=re.DOTALL)

    assert blocks
    for index, source in enumerate(blocks):
        compile(source, f"update.sh heredoc {index}", "exec")
