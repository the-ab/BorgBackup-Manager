#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="BorgBackup Manager"
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"

CURRENT_VERSION="$(cat VERSION 2>/dev/null || echo 0.0.0)"
UPDATE_DIR="${UPDATE_DIR:-updates}"
ASSUME_YES=0
NO_BUILD=0
FORCE_REBUILD=0
UPDATE_FILE=""
EXPECTED_SHA256="${BBM_UPDATE_SHA256:-}"
TS="$(date +%Y%m%d-%H%M%S)"
DC=()
PROJECT_BACKUP=""
CONTAINER_STOPPED=0
NEW_CONTAINER_STARTED=0
PROJECT_APPLIED=0
ACTIVE_PARTIAL=""

log() { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "FEHLER: $1" >&2; exit 1; }

usage() {
  cat <<USAGE
$APP_NAME Update

Verwendung:
  bash update.sh                 Neuestes gültiges ZIP aus updates/ installieren
  bash update.sh --file DATEI --sha256 SHA256
                                Angegebenes Release-ZIP nach Prüfsummenabgleich installieren
  bash update.sh --rebuild       Nur sichern, neu bauen und starten
  bash update.sh --yes           Rückfragen automatisch bestätigen
  bash update.sh --no-build      Nur Projektdateien aktualisieren
USAGE
}

while (($#)); do
  case "$1" in
    --file) shift; (($#)) || fail "--file benötigt einen Pfad"; UPDATE_FILE="$1" ;;
    --sha256) shift; (($#)) || fail "--sha256 benötigt eine Prüfsumme"; EXPECTED_SHA256="$1" ;;
    --rebuild) FORCE_REBUILD=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --no-build) NO_BUILD=1 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unbekannter Parameter: $1" ;;
  esac
  shift
done

need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "$1 wurde nicht gefunden"; }

env_value() {
  local key="$1" default="$2"
  if [[ -f .env ]] && grep -qE "^${key}=" .env; then
    grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2-
  else
    printf '%s' "$default"
  fi
}

confirm() {
  local answer
  ((ASSUME_YES)) && return 0
  read -r -p "$1 [J/n]: " answer
  answer="${answer:-J}"
  [[ "$answer" =~ ^[JjYy]$ ]]
}

detect_compose() {
  local prefix=()
  if docker info >/dev/null 2>&1; then
    prefix=()
  elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    prefix=(sudo)
  else
    fail "Docker-Daemon ist nicht erreichbar"
  fi
  if "${prefix[@]}" docker compose version >/dev/null 2>&1; then
    DC=("${prefix[@]}" docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    DC=("${prefix[@]}" docker-compose)
  else
    fail "Docker Compose wurde nicht gefunden"
  fi
}

compose() { "${DC[@]}" "$@"; }

version_gt() {
  python3 - "$1" "$2" <<'PY'
import re, sys

def version(value):
    numbers = [int(item) for item in re.findall(r"\d+", value or "")[:4]]
    return tuple(numbers + [0] * (4 - len(numbers)))

raise SystemExit(0 if version(sys.argv[1]) > version(sys.argv[2]) else 1)
PY
}

verify_package_checksum() {
  local package="$1" expected="$EXPECTED_SHA256" actual sidecar
  sidecar="${package}.sha256"
  if [[ -z "$expected" && -f "$sidecar" ]]; then
    expected="$(awk 'NR==1 {print $1}' "$sidecar")"
  fi
  if [[ -z "$expected" && -t 0 && "$ASSUME_YES" -eq 0 ]]; then
    read -r -p "Veröffentlichte SHA-256-Prüfsumme für $(basename "$package"): " expected
  fi
  expected="${expected,,}"
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || fail "Für das Release-ZIP ist eine vertrauenswürdig bezogene SHA-256-Prüfsumme erforderlich (--sha256 oder DATEI.sha256)"
  actual="$(sha256sum "$package" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || fail "SHA-256-Prüfung fehlgeschlagen: erwartet $expected, erhalten $actual"
  EXPECTED_SHA256="$expected"
  log "SHA-256-Prüfung erfolgreich: $actual"
}

zip_version() {
  python3 - "$1" <<'PY'
from pathlib import Path
import re, sys, zipfile

path = Path(sys.argv[1])
with zipfile.ZipFile(path) as archive:
    names = set(archive.namelist())
    candidates = []
    for name in names:
        if name != "VERSION" and not name.rstrip("/").endswith("/VERSION"):
            continue
        prefix = name[:-len("VERSION")]
        if prefix + "compose.yaml" in names and any(item.startswith(prefix + "app/") for item in names):
            candidates.append(name)
    if len(candidates) != 1:
        raise SystemExit(1)
    value = archive.read(candidates[0]).decode("utf-8", "replace").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", value):
        raise SystemExit(1)
    print(value)
PY
}

find_newest_zip() {
  mkdir -p "$UPDATE_DIR"
  python3 - "$UPDATE_DIR" "$CURRENT_VERSION" <<'PY'
from pathlib import Path
import re, sys, zipfile

directory = Path(sys.argv[1])
current = sys.argv[2]

def version(value):
    numbers = [int(item) for item in re.findall(r"\d+", value or "")[:4]]
    return tuple(numbers + [0] * (4 - len(numbers)))

updates = []
for path in directory.glob("*.zip"):
    try:
        sidecar = Path(str(path) + ".sha256")
        if not sidecar.is_file():
            continue
        expected = sidecar.read_text(encoding="utf-8").split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            continue
        import hashlib
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            continue
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            candidates = []
            for name in names:
                if name != "VERSION" and not name.rstrip("/").endswith("/VERSION"):
                    continue
                prefix = name[:-len("VERSION")]
                if prefix + "compose.yaml" in names and any(item.startswith(prefix + "app/") for item in names):
                    candidates.append(name)
            if len(candidates) != 1:
                continue
            value = archive.read(candidates[0]).decode("utf-8", "replace").strip()
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", value):
                continue
            if version(value) > version(current):
                updates.append((version(value), value, path))
    except (OSError, zipfile.BadZipFile):
        continue
if updates:
    _, value, path = max(updates, key=lambda item: (item[0], item[1], str(item[2])))
    print(f"{path}\t{value}")
PY
}

merge_env_example() {
  [[ -f .env && -f .env.example ]] || return 0
  python3 - .env .env.example "$(cat VERSION 2>/dev/null || echo unknown)" <<'PY'
from pathlib import Path
import re, sys

target, example, version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
current = target.read_text(encoding="utf-8").splitlines()
sample = example.read_text(encoding="utf-8").splitlines()
pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
# v1.0.21 changes only the unchanged historical default. Custom cookie names
# remain untouched. The new name avoids collisions with a stale Secure cookie.
migrated_cookie_name = False
for index, line in enumerate(current):
    if line.strip() == "BBM_SESSION_COOKIE_NAME=bbm_session":
        current[index] = "BBM_SESSION_COOKIE_NAME=bbm_session_v2"
        migrated_cookie_name = True
known = {match.group(1) for line in current if (match := pattern.match(line.strip()))}
required = {"BBM_REPOSITORY_PUBLIC_HOST", "BBM_DATA_PATH", "BBM_REPOSITORY_PATH"}
missing_required = sorted(required - known)
if missing_required:
    raise SystemExit(
        "Pflichtwert fehlt in .env: " + ", ".join(missing_required)
        + ". Bitte zuerst `bash install.sh --config-only` ausführen."
    )

blocks = []
pending_comments = []
for line in sample:
    stripped = line.strip()
    match = pattern.match(stripped)
    if match:
        key = match.group(1)
        if key not in known:
            block = [*pending_comments, line]
            blocks.append(block)
            known.add(key)
        pending_comments = []
    elif not stripped or stripped.startswith("#"):
        pending_comments.append(line)
    else:
        pending_comments = []

if blocks:
    if current and current[-1]:
        current.append("")
    current.append(f"# Automatisch ergänzt durch Update auf v{version}")
    for index, block in enumerate(blocks):
        if index and current and current[-1]:
            current.append("")
        while block and not block[0].strip():
            block.pop(0)
        current.extend(block)
if blocks or migrated_cookie_name:
    target.write_text("\n".join(current).rstrip() + "\n", encoding="utf-8")
if migrated_cookie_name:
    print("Standard-Sitzungscookie auf bbm_session_v2 migriert")
if blocks:
    print(f"{len(blocks)} neue .env-Werte ergänzt")
elif not migrated_cookie_name:
    print("Keine neuen .env-Werte erforderlich")
PY
}

cleanup_on_exit() {
  local rc=$?
  if [[ -n "$ACTIVE_PARTIAL" && -f "$ACTIVE_PARTIAL" ]]; then
    rm -f -- "$ACTIVE_PARTIAL" || true
  fi
  if ((rc != 0 && PROJECT_APPLIED && NEW_CONTAINER_STARTED == 0)); then
    restore_project_backup >/dev/null 2>&1 || \
      log "WARNUNG: Projektdateien konnten nach dem Abbruch nicht automatisch zurückgesetzt werden."
    PROJECT_APPLIED=0
  fi
  if ((rc != 0 && CONTAINER_STOPPED)); then
    log "Update wurde unterbrochen; der zuvor gestoppte Container wird wieder gestartet."
    compose start borg-manager >/dev/null 2>&1 || \
      log "WARNUNG: Der vorherige Container konnte nicht automatisch gestartet werden."
    CONTAINER_STOPPED=0
  fi
}
trap cleanup_on_exit EXIT

project_items() {
  printf '%s\n' \
    .dockerignore .env.example .gitattributes .gitignore .github \
    LICENSE NOTICE SECURITY.md CONTRIBUTING.md THIRD-PARTY-NOTICES.md pytest.ini scripts \
    compose.yaml Dockerfile install.sh update.sh recovery.sh restore-backup.sh INSTALLATION.md INSTALLATION.de.md README.md README.de.md \
    RELEASE_NOTES.md RELEASE_NOTES.de.md VERSION requirements.in requirements.txt requirements-dev.txt app docker tests
}

validate_runtime_paths() {
  local data_path repository_path data_abs repository_abs probe
  data_path="$(env_value BBM_DATA_PATH "")"
  repository_path="$(env_value BBM_REPOSITORY_PATH "")"
  [[ -n "$data_path" && -n "$repository_path" ]] \
    || fail "BBM_DATA_PATH und BBM_REPOSITORY_PATH müssen in .env gesetzt sein"
  [[ -d "$data_path" ]] || fail "Manager-Datenverzeichnis fehlt: $data_path"
  [[ -d "$repository_path" ]] || fail "Repository-Verzeichnis fehlt: $repository_path"
  data_abs="$(python3 - "$data_path" <<'PYDATA'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PYDATA
)"
  repository_abs="$(python3 - "$repository_path" <<'PYDATA'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PYDATA
)"
  [[ "$data_abs" != "$repository_abs" ]] \
    || fail "BBM_DATA_PATH und BBM_REPOSITORY_PATH dürfen nicht identisch sein"
  [[ "$data_abs/" != "$repository_abs/"* ]] \
    || fail "BBM_DATA_PATH darf nicht innerhalb von BBM_REPOSITORY_PATH liegen"
  mkdir -p "$data_path/update-backups"
  probe="$data_path/update-backups/.bbm-write-test-$$"
  : > "$probe" || fail "Update-Backupverzeichnis ist nicht beschreibbar: $data_path/update-backups"
  rm -f -- "$probe"
}

create_project_backup() {
  local data_path backup_dir backup_root items=()
  data_path="$(env_value BBM_DATA_PATH "$PROJECT_DIR/data")"
  backup_dir="$data_path/update-backups"
  backup_root="$backup_dir/update-${TS}-v${CURRENT_VERSION}"
  mkdir -p "$backup_root"
  while IFS= read -r item; do
    [[ -e "$item" ]] && items+=("$item")
  done < <(project_items)
  tar -czf "$backup_root/project-files.tar.gz" "${items[@]}"
  [[ -f .env ]] && cp .env "$backup_root/.env"
  chmod -R go-rwx "$backup_root" 2>/dev/null || true
  PROJECT_BACKUP="$backup_root"
  log "Projektstand gesichert: $backup_root"
}

create_data_backup() {
  local data_path repository_path data_abs repository_abs repository_relative archive partial size
  local -a excludes=(--one-file-system --exclude='./update-backups' --exclude='./borg-cache' --exclude='./archive-cache')
  data_path="$(env_value BBM_DATA_PATH "$PROJECT_DIR/data")"
  repository_path="$(env_value BBM_REPOSITORY_PATH "$PROJECT_DIR/repositories")"
  [[ -d "$data_path" ]] || return 0

  data_abs="$(python3 - "$data_path" <<'PYDATA'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PYDATA
)"
  repository_abs="$(python3 - "$repository_path" <<'PYDATA'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PYDATA
)"
  if [[ "$repository_abs" == "$data_abs" ]]; then
    fail "BBM_REPOSITORY_PATH darf für ein sicheres Update-Backup nicht identisch mit BBM_DATA_PATH sein"
  fi
  if [[ "$repository_abs" == "$data_abs/"* ]]; then
    repository_relative="${repository_abs#"$data_abs/"}"
    excludes+=(--exclude="./$repository_relative")
    log "Repository-Unterverzeichnis wird vom Manager-Datenbackup ausgeschlossen: $repository_relative"
  fi

  archive="$data_path/update-backups/update-${TS}-persistent-v${CURRENT_VERSION}.tar.gz"
  partial="$archive.partial"
  ACTIVE_PARTIAL="$partial"
  rm -f -- "$partial"
  log "Persistente Manager-Daten werden gesichert; Repository-Daten sowie regenerierbarer Borg- und Archivlisten-Cache werden ausgelassen."
  if ! tar "${excludes[@]}" -czf "$partial" -C "$data_path" .; then
    rm -f -- "$partial"
    fail "Persistente Manager-Daten konnten nicht gesichert werden"
  fi
  mv -- "$partial" "$archive"
  ACTIVE_PARTIAL=""
  chmod 600 "$archive" 2>/dev/null || true
  size="$(du -h "$archive" 2>/dev/null | awk '{print $1}' || true)"
  log "Persistente Manager-Daten gesichert: $archive${size:+ ($size)}"
  log "Repository-Daten sowie Borg- und Archivlisten-Cache wurden nicht kopiert oder verändert."
}

restore_project_backup() {
  [[ -n "$PROJECT_BACKUP" && -f "$PROJECT_BACKUP/project-files.tar.gz" ]] || return 1
  log "Vorherige Projektdateien werden wiederhergestellt..."
  while IFS= read -r item; do
    [[ "$item" != /* && "$item" != *".."* ]] || fail "Unsicherer Wiederherstellungspfad"
    rm -rf -- "$item"
  done < <(project_items)
  tar -xzf "$PROJECT_BACKUP/project-files.tar.gz" -C "$PROJECT_DIR"
  [[ -f "$PROJECT_BACKUP/.env" ]] && cp "$PROJECT_BACKUP/.env" .env
}

apply_zip() {
  local archive="$1" temp_dir
  temp_dir="$(mktemp -d)"
  if ! python3 - "$archive" "$temp_dir" "$PROJECT_DIR" <<'PY'
from pathlib import Path
import shutil, stat, sys, zipfile

archive_path = Path(sys.argv[1]).resolve()
temporary = Path(sys.argv[2]).resolve()
target = Path(sys.argv[3]).resolve()
extract = temporary / "extract"
extract.mkdir(parents=True)

with zipfile.ZipFile(archive_path) as archive:
    seen = set()
    for item in archive.infolist():
        parts = Path(item.filename).parts
        if not item.filename or item.filename.startswith(("/", "\\")) or ".." in parts:
            raise SystemExit(f"Unsicherer ZIP-Pfad: {item.filename}")
        if item.filename in seen:
            raise SystemExit(f"Doppelter ZIP-Eintrag: {item.filename}")
        seen.add(item.filename)
        mode = (item.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise SystemExit(f"Symbolische Links sind im Release-ZIP nicht erlaubt: {item.filename}")
    archive.extractall(extract)

candidates = [path.parent for path in extract.rglob("VERSION") if (path.parent / "compose.yaml").is_file() and (path.parent / "app").is_dir()]
if len(candidates) != 1:
    raise SystemExit("Release-ZIP enthält keinen eindeutigen BorgBackup-Manager-Projektordner")
source = candidates[0]
required = [
    ".env.example", "VERSION", "compose.yaml", "Dockerfile", "requirements.in", "requirements.txt", "app", "docker",
    "install.sh", "update.sh", "recovery.sh", "restore-backup.sh",
    "LICENSE", "NOTICE", "SECURITY.md", "CONTRIBUTING.md", "THIRD-PARTY-NOTICES.md",
    "README.md", "README.de.md", "INSTALLATION.md", "INSTALLATION.de.md", "RELEASE_NOTES.md", "RELEASE_NOTES.de.md",
]
missing = [name for name in required if not (source / name).exists()]
if missing:
    raise SystemExit("Release-ZIP ist unvollstaendig; fehlt: " + ", ".join(missing))
allowed = [
    ".dockerignore", ".env.example", ".gitattributes", ".gitignore", ".github",
    "LICENSE", "NOTICE", "SECURITY.md", "CONTRIBUTING.md", "THIRD-PARTY-NOTICES.md", "pytest.ini", "scripts",
    "compose.yaml", "Dockerfile", "install.sh", "update.sh", "recovery.sh", "restore-backup.sh", "INSTALLATION.md",
    "INSTALLATION.de.md", "README.md", "README.de.md", "RELEASE_NOTES.md", "RELEASE_NOTES.de.md",
    "VERSION", "requirements.in", "requirements.txt",
    "requirements-dev.txt", "app", "docker", "tests",
]
for name in allowed:
    src, dst = source / name, target / name
    if not src.exists():
        continue
    if dst.exists() or dst.is_symlink():
        shutil.rmtree(dst) if dst.is_dir() and not dst.is_symlink() else dst.unlink()
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
for name in ("install.sh", "update.sh", "recovery.sh", "restore-backup.sh", "docker/entrypoint.sh", "docker/borg-serve.sh"):
    path = target / name
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
legacy_english_notes = target / "RELEASE_NOTES.en.md"
if legacy_english_notes.exists() or legacy_english_notes.is_symlink():
    legacy_english_notes.unlink()
PY
  then
    rm -rf -- "$temp_dir"
    return 1
  fi
  rm -rf -- "$temp_dir"
}

probe_https_endpoint() {
  local endpoint="$1" port output
  port="$(env_value BBM_HTTPS_PORT 8443)"
  [[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1 && port <= 65535)) \
    || { printf 'Ungültiger BBM_HTTPS_PORT: %s' "$port"; return 1; }

  # Zuerst den veröffentlichten Host-Port prüfen. Das entspricht exakt dem
  # Zugriff des Browsers und vermeidet falsche Fehler durch ein kurzzeitig
  # noch nicht verfügbares `docker compose exec` nach dem Recreate.
  if output="$(python3 - "$port" "$endpoint" <<'PYHTTP' 2>&1
import ssl
import sys
import urllib.error
import urllib.request

port, endpoint = sys.argv[1], sys.argv[2]
url = f"https://127.0.0.1:{port}{endpoint}"
context = ssl._create_unverified_context()
try:
    with urllib.request.urlopen(url, context=context, timeout=3) as response:
        body = response.read(1024).decode("utf-8", "replace").strip().replace("\n", " ")
        content_type = response.headers.get_content_type()
        if endpoint == "/" or content_type == "text/html":
            print(f"HTTP {response.status}")
        else:
            print(f"HTTP {response.status}: {body[:512]}")
        raise SystemExit(0 if 200 <= response.status < 300 else 1)
except urllib.error.HTTPError as exc:
    print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}")
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}")
raise SystemExit(1)
PYHTTP
  )"; then
    printf '%s' "$output"
    return 0
  fi

  # Fallback: interner HTTPS-Aufruf im Container, falls der veröffentlichte
  # Port absichtlich nur an eine besondere Adresse gebunden ist.
  if output="$(compose exec -T borg-manager python - "$endpoint" <<'PYHTTP' 2>&1
import ssl
import sys
import urllib.error
import urllib.request

endpoint = sys.argv[1]
url = f"https://127.0.0.1:8443{endpoint}"
context = ssl._create_unverified_context()
try:
    with urllib.request.urlopen(url, context=context, timeout=3) as response:
        body = response.read(1024).decode("utf-8", "replace").strip().replace("\n", " ")
        content_type = response.headers.get_content_type()
        if endpoint == "/" or content_type == "text/html":
            print(f"HTTP {response.status}")
        else:
            print(f"HTTP {response.status}: {body[:512]}")
        raise SystemExit(0 if 200 <= response.status < 300 else 1)
except urllib.error.HTTPError as exc:
    print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}")
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}")
raise SystemExit(1)
PYHTTP
  )"; then
    printf '%s' "$output"
    return 0
  fi

  printf '%s' "$output"
  return 1
}

wait_for_health() {
  local attempt last_result="Noch keine Antwort" legacy_result=""
  for attempt in {1..90}; do
    if last_result="$(probe_https_endpoint /api/ready)"; then
      log "Web-Bereitschaft bestätigt: $last_result"
      return 0
    fi

    if (( attempt == 10 || attempt == 30 || attempt == 60 )); then
      log "Containerstart läuft noch (Bereitschaftsprüfung $attempt/90): $last_result"
      compose ps borg-manager || true
      compose logs --tail=20 borg-manager || true
    fi

    # Erst auf den aktuellen Readiness-Endpunkt warten. Der Startseiten-
    # Fallback ist nur für ein tatsächliches Rollback auf alte Versionen.
    if (( attempt >= 15 )); then
      if legacy_result="$(probe_https_endpoint /)"; then
        log "Web-Bereitschaft über kompatiblen Startseiten-Test bestätigt: $legacy_result"
        return 0
      fi
    fi
    sleep 1
  done
  log "Letzte Bereitschaftsprüfung: $last_result"
  [[ -z "$legacy_result" ]] || log "Letzter kompatibler Startseiten-Test: $legacy_result"
  return 1
}

report_authentication_health() {
  local result
  if result="$(compose exec -T borg-manager python -m app.account_recovery status --json 2>&1)"; then
    log "Anmeldeprüfung: $result"
  else
    log "WARNUNG: Die lokale Benutzerprüfung meldet einen nicht bereiten Zustand: $result"
    log "Konten prüfen: docker compose exec -T borg-manager python -m app.account_recovery status"
    log "Adminzugang zurücksetzen: docker compose exec -T borg-manager python -m app.account_recovery reset admin --admin"
  fi
}

report_component_health() {
  local result
  if result="$(probe_https_endpoint /api/health/strict)"; then
    log "Komponentenprüfung: $result"
  else
    log "WARNUNG: WebUI ist bereit, aber die Komponentenprüfung meldet einen eingeschränkten Zustand: $result"
    log "Das Update wird nicht zurückgerollt. Details stehen unter Systemdiagnose und in den Container-Logs."
  fi
}

build_and_start() {
  if ! compose config --quiet; then
    restore_project_backup || true
    PROJECT_APPLIED=0
    fail "Docker-Compose-Konfiguration ist ungueltig; Projektdateien wurden zurueckgesetzt"
  fi
  log "Neues Container-Image wird gebaut; der laufende Container bleibt dabei aktiv."
  if ! compose build --pull; then
    restore_project_backup || true
    PROJECT_APPLIED=0
    fail "Image-Build fehlgeschlagen; Projektdateien wurden zurückgesetzt"
  fi

  log "Container wird für konsistente Sicherung der Manager-Daten gestoppt."
  compose stop borg-manager || fail "Container konnte nicht kontrolliert gestoppt werden"
  CONTAINER_STOPPED=1
  create_data_backup

  if compose up -d --remove-orphans --force-recreate; then
    CONTAINER_STOPPED=0
    NEW_CONTAINER_STARTED=1
  fi
  if ((CONTAINER_STOPPED == 0)) && wait_for_health; then
    report_component_health
    report_authentication_health
    log "Neuer Container ist fehlerfrei gestartet."
    return 0
  fi

  log "Neustart oder Health-Check fehlgeschlagen. Rollback wird ausgeführt."
  compose logs --tail=100 borg-manager || true
  restore_project_backup || fail "Projekt-Rollback konnte nicht ausgeführt werden"
  PROJECT_APPLIED=0
  NEW_CONTAINER_STARTED=0
  compose build
  compose up -d --remove-orphans --force-recreate
  CONTAINER_STOPPED=0
  wait_for_health || fail "Auch die vorherige Version wurde nicht gesund; Backup liegt unter $PROJECT_BACKUP"
  fail "Update fehlgeschlagen; vorherige Projektversion wurde wieder gestartet"
}

main() {
  need_cmd python3
  need_cmd tar
  need_cmd docker
  need_cmd sha256sum
  [[ -f .env ]] || fail ".env fehlt; zuerst bash install.sh ausführen"
  detect_compose
  validate_runtime_paths
  mkdir -p "$UPDATE_DIR"

  local package="" target_version="" newest="" did_update=0 installed_package=""
  if [[ -n "$UPDATE_FILE" ]]; then
    package="$UPDATE_FILE"
    [[ -f "$package" ]] || fail "Update-ZIP nicht gefunden: $package"
    verify_package_checksum "$package"
    target_version="$(zip_version "$package")" || fail "VERSION im ZIP fehlt oder ist ungültig"
  elif ((FORCE_REBUILD == 0)); then
    newest="$(find_newest_zip)"
    if [[ -n "$newest" ]]; then
      package="${newest%%$'\t'*}"
      target_version="${newest#*$'\t'}"
      verify_package_checksum "$package"
    fi
  fi

  if [[ -n "$package" ]]; then
    version_gt "$target_version" "$CURRENT_VERSION" \
      || fail "Paketversion v$target_version ist nicht neuer als v$CURRENT_VERSION"
    log "Update gefunden: v$CURRENT_VERSION -> v$target_version ($package)"
    confirm "Update installieren?" || { log "Update abgebrochen"; exit 0; }
    create_project_backup
    if ! apply_zip "$package"; then
      restore_project_backup || true
      fail "Release-ZIP konnte nicht sicher installiert werden"
    fi
    PROJECT_APPLIED=1
    if ! merge_env_example; then
      restore_project_backup || true
      PROJECT_APPLIED=0
      fail ".env konnte nicht sicher ergänzt werden"
    fi
    did_update=1
  elif ((FORCE_REBUILD)); then
    log "Rebuild der aktuellen Version v$CURRENT_VERSION"
    create_project_backup
    PROJECT_APPLIED=1
    if ! merge_env_example; then
      restore_project_backup || true
      PROJECT_APPLIED=0
      fail ".env konnte nicht sicher ergänzt werden"
    fi
  else
    log "Kein neueres Release-ZIP unter $UPDATE_DIR gefunden."
    confirm "Aktuelle Version trotzdem sichern und neu bauen?" || exit 0
    create_project_backup
    PROJECT_APPLIED=1
    if ! merge_env_example; then
      restore_project_backup || true
      PROJECT_APPLIED=0
      fail ".env konnte nicht sicher ergänzt werden"
    fi
  fi

  if ((NO_BUILD)); then
    log "--no-build: Projektdateien aktualisiert, Container unverändert."
  else
    build_and_start
  fi

  if ((did_update)); then
    mkdir -p "$UPDATE_DIR/installed"
    installed_package="$UPDATE_DIR/installed/$(basename "$package" .zip)-installed-${TS}.zip"
    mv -- "$package" "$installed_package"
    printf '%s  %s\n' "$EXPECTED_SHA256" "$(basename "$installed_package")" > "${installed_package}.sha256"
    rm -f -- "${package}.sha256"
  fi

  CURRENT_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
  log "Update-/Wartungsprozess erfolgreich abgeschlossen: v$CURRENT_VERSION"
  printf '\nStatus:\n  %s ps\n  %s logs -f borg-manager\n' "${DC[*]}" "${DC[*]}"
  printf '\nUpdate-Verzeichnis:\n  %s/%s\n' "$PROJECT_DIR" "$UPDATE_DIR"
  printf '\nLetztes Backup:\n  %s\n' "$PROJECT_BACKUP"
}

main
