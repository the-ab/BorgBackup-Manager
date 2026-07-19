#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
umask 077
DEFAULT_BASE_PATH="/docker_data/borgbackup-manager"
DEFAULT_DATA_PATH="$DEFAULT_BASE_PATH/data"
DEFAULT_REPOSITORY_PATH="$DEFAULT_BASE_PATH/repositories"
DEFAULT_TIMEZONE="Europe/Berlin"

fail() { echo "Fehler: $*" >&2; exit 1; }
[[ $# -eq 1 ]] || fail "Verwendung: bash restore-backup.sh /pfad/borgbackup-manager-backup-....zip|.bbm"
BACKUP_FILE="$(readlink -f -- "$1" 2>/dev/null || true)"
[[ -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]] || fail "Backup-Datei nicht gefunden: $1"
command -v python3 >/dev/null 2>&1 || fail "python3 wird benötigt"
[[ -f install.sh ]] || fail "install.sh fehlt im Projektordner"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

backup_passphrase=""
if [ "$(head -c 13 -- "$BACKUP_FILE" 2>/dev/null || true)" = "BBM-BACKUP-1" ]; then
  python3 -c 'import cryptography' >/dev/null 2>&1 || fail "Verschlüsseltes Backup benötigt python3-cryptography (Debian: apt install python3-cryptography)"
  read -r -s -p "Backup-Passphrase: " backup_passphrase
  echo
  [ -n "$backup_passphrase" ] || fail "Backup-Passphrase darf nicht leer sein"
fi
export BBM_RESTORE_BACKUP_PASSPHRASE="$backup_passphrase"

python3 - "$BACKUP_FILE" "$TMP_DIR" <<'PY'
from pathlib import Path, PurePosixPath
import base64, io, json, os, stat, struct, sys, zipfile

source, destination = Path(sys.argv[1]), Path(sys.argv[2])
magic = b"BBM-BACKUP-1\n"
max_file_bytes = int(os.environ.get("BBM_BACKUP_MAX_FILE_BYTES", "268435456"))
max_uncompressed_bytes = int(os.environ.get("BBM_BACKUP_MAX_UNCOMPRESSED_BYTES", "1073741824"))
max_entries = int(os.environ.get("BBM_BACKUP_MAX_ENTRIES", "5000"))
max_compression_ratio = int(os.environ.get("BBM_BACKUP_MAX_COMPRESSION_RATIO", "250"))

if source.stat().st_size > max_file_bytes:
    raise SystemExit(f"Backup-Datei überschreitet das Größenlimit von {max_file_bytes} Bytes")

with source.open("rb") as handle:
    prefix = handle.read(len(magic))

archive_source: Path | io.BytesIO
if prefix == magic:
    raw = source.read_bytes()
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise SystemExit("python3-cryptography fehlt") from exc
    if len(raw) < len(magic) + 4:
        raise SystemExit("Verschlüsselter Backup-Header ist unvollständig")
    header_length = struct.unpack(">I", raw[len(magic):len(magic)+4])[0]
    if header_length < 32 or header_length > 65_536:
        raise SystemExit("Verschlüsselter Backup-Header hat eine ungültige Größe")
    header_end = len(magic) + 4 + header_length
    if header_end > len(raw):
        raise SystemExit("Verschlüsselter Backup-Header ist unvollständig")
    header_bytes = raw[len(magic)+4:header_end]
    try:
        header = json.loads(header_bytes)
        if not isinstance(header, dict):
            raise TypeError
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Verschlüsselter Backup-Header ist ungültig") from exc
    passphrase = os.environ.get("BBM_RESTORE_BACKUP_PASSPHRASE", "")
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())
    try:
        decrypted = AESGCM(key).decrypt(nonce, raw[header_end:], raw[:header_end])
    except Exception as exc:
        raise SystemExit("Backup-Passphrase ist falsch oder das Backup wurde verändert") from exc
    if not decrypted.startswith(b"PK"):
        raise SystemExit("Entschlüsseltes Backup ist kein gültiges ZIP-Archiv")
    archive_source = io.BytesIO(decrypted)
else:
    archive_source = source


def safe_relative_path(raw_path: str, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path or "\\" in raw_path:
        raise SystemExit(f"Unsicherer {label}: {raw_path!r}")
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SystemExit(f"Unsicherer {label}: {raw_path}")
    relative = Path(*pure.parts)
    target = (destination / relative).resolve(strict=False)
    root = destination.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"Unsicherer {label}: {raw_path}") from exc
    return relative


with zipfile.ZipFile(archive_source) as archive:
    entries = archive.infolist()
    if len(entries) > max_entries:
        raise SystemExit(f"Backup enthält mehr als {max_entries} ZIP-Einträge")
    seen: set[str] = set()
    total_uncompressed = 0
    for item in entries:
        relative = safe_relative_path(item.filename.rstrip("/"), "ZIP-Pfad")
        normalized = relative.as_posix()
        if normalized in seen:
            raise SystemExit(f"Doppelter oder kollidierender ZIP-Eintrag: {item.filename}")
        seen.add(normalized)
        mode = (item.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise SystemExit(f"Symbolische Links sind im Backup nicht erlaubt: {item.filename}")
        if item.is_dir():
            continue
        total_uncompressed += item.file_size
        if total_uncompressed > max_uncompressed_bytes:
            raise SystemExit(f"Backup überschreitet entpackt das Größenlimit von {max_uncompressed_bytes} Bytes")
        if item.file_size and item.file_size / max(item.compress_size, 1) > max_compression_ratio:
            raise SystemExit(f"ZIP-Eintrag überschreitet das Kompressionslimit: {item.filename}")
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, ValueError) as exc:
        raise SystemExit("Manifest fehlt oder ist ungültig") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "borgbackup-manager-full-backup":
        raise SystemExit("Datei ist kein BorgBackup-Manager-Vollbackup")
    archive.extractall(destination)

permissions_path = destination / "permissions.json"
if permissions_path.is_file():
    try:
        permissions = json.loads(permissions_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("permissions.json ist ungültig") from exc
    if not isinstance(permissions, dict) or len(permissions) > max_entries:
        raise SystemExit("permissions.json hat ein ungültiges Format oder zu viele Einträge")
    for relative, mode in permissions.items():
        relative_path = safe_relative_path(relative, "Berechtigungspfad")
        if isinstance(mode, bool) or not isinstance(mode, int) or mode < 0 or mode > 0o7777:
            raise SystemExit(f"Ungültiger Dateimodus für {relative}")
        path = destination / relative_path
        if path.is_file() and not path.is_symlink():
            os.chmod(path, mode & 0o777)
if not (destination / "migration.env").is_file():
    raise SystemExit("Backup enthält keine migration.env")
if not (destination / "data").is_dir():
    raise SystemExit("Backup enthält kein Manager-Datenverzeichnis")
print(f"Backup v{manifest.get('app_version', '?')} vom {manifest.get('created_at', '?')} geprüft.")
PY
PY
unset BBM_RESTORE_BACKUP_PASSPHRASE backup_passphrase

env_value() {
  local key="$1" default="$2" value
  value="$(sed -n "s/^${key}=//p" "$TMP_DIR/migration.env" | tail -n 1)"
  printf '%s' "${value:-$default}"
}

prompt() {
  local variable="$1" label="$2" default="$3" value
  read -r -p "$label [$default]: " value
  printf -v "$variable" '%s' "${value:-$default}"
}

prompt BBM_DATA_PATH "Neues persistentes Manager-Datenverzeichnis" "$(env_value BBM_DATA_PATH "$DEFAULT_DATA_PATH")"
prompt BBM_REPOSITORY_PATH "Verzeichnismount mit den vorhandenen Borg-Repositories" "$(env_value BBM_REPOSITORY_PATH "$DEFAULT_REPOSITORY_PATH")"
prompt BBM_REPOSITORY_PUBLIC_HOST "Vom Client erreichbarer DNS-Name / IP des neuen Servers" "$(env_value BBM_REPOSITORY_PUBLIC_HOST "$(hostname -f 2>/dev/null || hostname)")"
prompt BBM_HTTPS_PORT "HTTPS-WebUI-Port" "$(env_value BBM_HTTPS_PORT "$(env_value BBM_HTTP_PORT 8443)")"
prompt BBM_REPOSITORY_SSH_PORT "Repository-SSH-Port" "$(env_value BBM_REPOSITORY_SSH_PORT 2222)"

[[ "$BBM_DATA_PATH" == /* && "$BBM_REPOSITORY_PATH" == /* ]] || fail "Daten- und Repository-Pfad müssen absolut sein"
[[ "$BBM_DATA_PATH" != "$BBM_REPOSITORY_PATH" ]] || fail "Daten- und Repository-Pfad dürfen nicht identisch sein"
[[ "$BBM_DATA_PATH/" != "$BBM_REPOSITORY_PATH/"* ]] || fail "Das Manager-Datenverzeichnis darf nicht innerhalb des Repository-Verzeichnisses liegen"
RESTORE_TIMEZONE="$(env_value TZ "$DEFAULT_TIMEZONE")"
[[ -n "$RESTORE_TIMEZONE" && "$RESTORE_TIMEZONE" =~ ^[A-Za-z0-9_+./-]+$ && "$RESTORE_TIMEZONE" != /* && "$RESTORE_TIMEZONE" != *'..'* ]] \
  || fail "Zeitzone im Backup ist ungültig: $RESTORE_TIMEZONE"
mkdir -p -- "$BBM_DATA_PATH" "$BBM_REPOSITORY_PATH"
if find "$BBM_DATA_PATH" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  SAFETY_COPY="${BBM_DATA_PATH%/}-vor-restore-$(date +%Y%m%d-%H%M%S)"
  echo "Vorhandene Manager-Daten werden nach $SAFETY_COPY verschoben."
  mv -- "$BBM_DATA_PATH" "$SAFETY_COPY"
  mkdir -p -- "$BBM_DATA_PATH"
fi
cp -a -- "$TMP_DIR/data/." "$BBM_DATA_PATH/"

LEGACY_ADMIN_TOKEN="$(env_value BBM_ADMIN_TOKEN '')"
LEGACY_SECRET_KEY="$(env_value BBM_SECRET_KEY '')"
cat > .env <<EOF
TZ=$RESTORE_TIMEZONE
BBM_HTTPS_PORT=$BBM_HTTPS_PORT
BBM_TLS_HOSTS=$(env_value BBM_TLS_HOSTS "$BBM_REPOSITORY_PUBLIC_HOST")
BBM_SESSION_TTL_SECONDS=$(env_value BBM_SESSION_TTL_SECONDS 86400)
BBM_SESSION_IDLE_TIMEOUT_SECONDS=$(env_value BBM_SESSION_IDLE_TIMEOUT_SECONDS 3600)
BBM_SESSION_COOKIE_NAME=$(env_value BBM_SESSION_COOKIE_NAME bbm_session_v2)
BBM_SESSION_COOKIE_SECURE=$(env_value BBM_SESSION_COOKIE_SECURE always)
BBM_TRUSTED_PROXY_CIDRS=$(env_value BBM_TRUSTED_PROXY_CIDRS '127.0.0.1/32,::1/128')
BBM_LOGIN_RATE_WINDOW_SECONDS=$(env_value BBM_LOGIN_RATE_WINDOW_SECONDS 300)
BBM_LOGIN_RATE_BLOCK_SECONDS=$(env_value BBM_LOGIN_RATE_BLOCK_SECONDS 900)
BBM_LOGIN_RATE_MAX_PER_IP=$(env_value BBM_LOGIN_RATE_MAX_PER_IP 20)
BBM_LOGIN_RATE_MAX_PER_IP_USER=$(env_value BBM_LOGIN_RATE_MAX_PER_IP_USER 5)
BBM_SECURITY_EVENT_RETENTION_DAYS=$(env_value BBM_SECURITY_EVENT_RETENTION_DAYS 90)
BBM_SECURITY_EVENT_MAX_ROWS=$(env_value BBM_SECURITY_EVENT_MAX_ROWS 10000)
BBM_BACKUP_MAX_FILE_BYTES=$(env_value BBM_BACKUP_MAX_FILE_BYTES 268435456)
BBM_BACKUP_MAX_UNCOMPRESSED_BYTES=$(env_value BBM_BACKUP_MAX_UNCOMPRESSED_BYTES 1073741824)
BBM_BACKUP_MAX_ENTRIES=$(env_value BBM_BACKUP_MAX_ENTRIES 5000)
BBM_BACKUP_MAX_COMPRESSION_RATIO=$(env_value BBM_BACKUP_MAX_COMPRESSION_RATIO 250)
BBM_COMMAND_TIMEOUT=$(env_value BBM_COMMAND_TIMEOUT 86400)
BBM_APPEARANCE=$(env_value BBM_APPEARANCE auto)
BBM_REPOSITORY_SIZE_AFTER_RUN=$(env_value BBM_REPOSITORY_SIZE_AFTER_RUN 1)
BBM_REPOSITORY_PUBLIC_HOST=$BBM_REPOSITORY_PUBLIC_HOST
BBM_REPOSITORY_SSH_PORT=$BBM_REPOSITORY_SSH_PORT
BBM_DATA_PATH=$BBM_DATA_PATH
BBM_REPOSITORY_PATH=$BBM_REPOSITORY_PATH
BBM_BORG_UID=$(env_value BBM_BORG_UID 1000)
BBM_BORG_GID=$(env_value BBM_BORG_GID 1000)
BBM_STORAGE_GUARD_ENABLED=$(env_value BBM_STORAGE_GUARD_ENABLED 1)
BBM_STORAGE_GUARD_THRESHOLD_PERCENT=$(env_value BBM_STORAGE_GUARD_THRESHOLD_PERCENT 95)
BBM_HEALTH_REQUIRE_SSHD=$(env_value BBM_HEALTH_REQUIRE_SSHD 1)
BBM_LOG_MAX_BYTES=$(env_value BBM_LOG_MAX_BYTES 10485760)
BBM_LOG_ROTATIONS=$(env_value BBM_LOG_ROTATIONS 5)
EOF
# Legacy values are only retained when restoring a pre-0.9 backup. The first
# 0.9 startup migrates credentials and repository secrets into /data/security.
if [[ -n "$LEGACY_ADMIN_TOKEN" ]]; then printf 'BBM_ADMIN_TOKEN=%s\n' "$LEGACY_ADMIN_TOKEN" >> .env; fi
if [[ -n "$LEGACY_SECRET_KEY" ]]; then printf 'BBM_SECRET_KEY=%s\n' "$LEGACY_SECRET_KEY" >> .env; fi
chmod 600 .env

echo "Manager-Daten wiederhergestellt. Installation wird mit Sicherheitsdatenbank und Master-Key abgeschlossen."
BBM_INSTALL_NONINTERACTIVE=1 bash install.sh
