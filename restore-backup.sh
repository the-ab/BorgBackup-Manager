#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
umask 077
DEFAULT_BASE_PATH="/docker_data/borgbackup-manager"
DEFAULT_DATA_PATH="$DEFAULT_BASE_PATH/data"
DEFAULT_REPOSITORY_PATH="$DEFAULT_BASE_PATH/repositories"
DEFAULT_ARCHIVE_MOUNT_PATH="$DEFAULT_BASE_PATH/archive-mounts"
MIN_SUPPORTED_BACKUP_VERSION="1.3.5"
DEFAULT_TIMEZONE="Europe/Berlin"

fail() { echo "Fehler: $*" >&2; exit 1; }
[[ $# -eq 1 ]] || fail "Verwendung: bash restore-backup.sh /pfad/borgbackup-manager-backup-....bbm"
BACKUP_FILE="$(readlink -f -- "$1" 2>/dev/null || true)"
[[ -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]] || fail "Backup-Datei nicht gefunden: $1"
command -v python3 >/dev/null 2>&1 || fail "python3 wird benötigt"
[[ -f install.sh ]] || fail "install.sh fehlt im Projektordner"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

backup_passphrase="${BBM_RESTORE_BACKUP_PASSPHRASE:-}"
if python3 - "$BACKUP_FILE" <<'PYMAGIC'
from pathlib import Path
import sys
raise SystemExit(0 if Path(sys.argv[1]).read_bytes()[:13] == b"BBM-BACKUP-1\n" else 1)
PYMAGIC
then
  python3 -c 'import cryptography' >/dev/null 2>&1 || fail "Verschlüsseltes Backup benötigt python3-cryptography (Debian: apt install python3-cryptography)"
  if [ -z "$backup_passphrase" ]; then
    read -r -s -p "Backup-Passphrase: " backup_passphrase
    echo
  fi
  [ -n "$backup_passphrase" ] || fail "Backup-Passphrase darf nicht leer sein"
fi
export BBM_RESTORE_BACKUP_PASSPHRASE="$backup_passphrase"

python3 - "$BACKUP_FILE" "$TMP_DIR" <<'PY'
from pathlib import Path, PurePosixPath
import base64, io, json, os, sqlite3, stat, struct, sys, zipfile

source, destination = Path(sys.argv[1]), Path(sys.argv[2])
magic = b"BBM-BACKUP-1\n"
max_file_bytes = int(os.environ.get("BBM_BACKUP_MAX_FILE_BYTES", "268435456"))
max_uncompressed_bytes = int(os.environ.get("BBM_BACKUP_MAX_UNCOMPRESSED_BYTES", "1073741824"))
max_entries = int(os.environ.get("BBM_BACKUP_MAX_ENTRIES", "5000"))
max_cache_file_bytes = int(os.environ.get("BBM_BACKUP_CACHE_MAX_FILE_BYTES", "34359738368"))
max_cache_uncompressed_bytes = int(os.environ.get("BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES", "137438953472"))
max_cache_entries = int(os.environ.get("BBM_BACKUP_CACHE_MAX_ENTRIES", "250000"))
max_compression_ratio = int(os.environ.get("BBM_BACKUP_MAX_COMPRESSION_RATIO", "250"))
max_cache_compression_ratio = int(os.environ.get("BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO", "5000"))

minimum_supported_version = (1, 3, 5)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as exc:
    raise SystemExit("python3-cryptography fehlt") from exc

def version_tuple(value):
    import re
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", str(value or "").strip())
    if not match:
        raise SystemExit("Backup enthält keine gültige BorgBackup-Manager-Version")
    return tuple(int(part) for part in match.groups())

def require_supported_version(metadata):
    if version_tuple(metadata.get("app_version")) < minimum_supported_version:
        raise SystemExit("Backups vor BorgBackup Manager v1.3.5 werden nicht mehr unterstützt")

with source.open("rb") as handle:
    prefix = handle.read(len(magic))

archive_source: Path | io.BytesIO
include_cache = False
if prefix == magic:
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise SystemExit("python3-cryptography fehlt") from exc
    with source.open("rb") as handle:
        if handle.read(len(magic)) != magic:
            raise SystemExit("Verschlüsselter Backup-Header ist ungültig")
        raw_length = handle.read(4)
        if len(raw_length) != 4:
            raise SystemExit("Verschlüsselter Backup-Header ist unvollständig")
        header_length = struct.unpack(">I", raw_length)[0]
        if header_length < 32 or header_length > 65_536:
            raise SystemExit("Verschlüsselter Backup-Header hat eine ungültige Größe")
        header_bytes = handle.read(header_length)
        if len(header_bytes) != header_length:
            raise SystemExit("Verschlüsselter Backup-Header ist unvollständig")
    header_end = len(magic) + 4 + header_length
    try:
        header = json.loads(header_bytes)
        if not isinstance(header, dict):
            raise TypeError
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Verschlüsselter Backup-Header ist ungültig") from exc
    require_supported_version(header)
    if header.get("format_version") != 2 or header.get("cipher") != "AES-256-GCM-stream":
        raise SystemExit("Backup verwendet ein nicht mehr unterstütztes Verschlüsselungsformat")
    if header.get("backup_type") == "cache" or header.get("content_format") == "borgbackup-manager-cache-backup":
        raise SystemExit(
            "Diese Datei ist ein separates Cache-Backup und kein Manager-Vollbackup. "
            "Cache-Daten nach der BBM-Wiederherstellung über die WebUI gezielt zurückspielen."
        )
    include_cache = bool(header.get("borg_cache_included") or header.get("client_borg_cache_included"))
    file_limit = max_cache_file_bytes if include_cache else max_file_bytes
    if source.stat().st_size > file_limit:
        raise SystemExit(f"Backup-Datei überschreitet das Größenlimit von {file_limit} Bytes")
    passphrase = os.environ.get("BBM_RESTORE_BACKUP_PASSPHRASE", "")
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())
    aad = magic + raw_length + header_bytes
    tag_bytes = int(header.get("tag_bytes", 16))
    if tag_bytes != 16:
        raise SystemExit("Ungültige GCM-Tag-Größe im Backup")
    size = source.stat().st_size
    ciphertext_size = size - header_end - tag_bytes
    if ciphertext_size <= 0:
        raise SystemExit("Verschlüsseltes Backup ist unvollständig")
    decrypted_path = destination / ".manager-backup-decrypted.zip"
    with source.open("rb") as encrypted:
        encrypted.seek(size - tag_bytes)
        tag = encrypted.read(tag_bytes)
        encrypted.seek(header_end)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(aad)
        remaining = ciphertext_size
        try:
            with decrypted_path.open("wb") as output:
                while remaining > 0:
                    chunk = encrypted.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise SystemExit("Verschlüsseltes Backup ist unvollständig")
                    remaining -= len(chunk)
                    output.write(decryptor.update(chunk))
                output.write(decryptor.finalize())
        except InvalidTag as exc:
            decrypted_path.unlink(missing_ok=True)
            raise SystemExit("Backup-Passphrase ist falsch oder das Backup wurde verändert") from exc
    archive_source = decrypted_path

else:
    raise SystemExit(
        "Unverschlüsselte Manager-ZIP-Backups vor der v1.3.5-Baseline werden nicht mehr unterstützt. "
        "Verwenden Sie ein aktuelles verschlüsseltes .bbm-Manager-Backup."
    )


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
    try:
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size < 2 or manifest_info.file_size > 1024 * 1024:
            raise ValueError
        manifest = json.loads(archive.read(manifest_info))
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("Manifest fehlt oder ist ungültig") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "borgbackup-manager-full-backup":
        raise SystemExit("Datei ist kein BorgBackup-Manager-Vollbackup")
    require_supported_version(manifest)
    if int(manifest.get("format_version") or 0) != 7:
        raise SystemExit("Manager-Backup verwendet ein Format vor der v1.3.5-Baseline")
    if manifest.get("backup_type") != "manager":
        raise SystemExit("Backup enthält keinen aktuellen Manager-Backup-Typ")
    include_cache = bool(manifest.get("borg_cache_included") or manifest.get("client_borg_cache_included"))
    entry_limit = max_cache_entries if include_cache else max_entries
    uncompressed_limit = max_cache_uncompressed_bytes if include_cache else max_uncompressed_bytes
    compression_ratio_limit = max_cache_compression_ratio if include_cache else max_compression_ratio
    entries = archive.infolist()
    if len(entries) > entry_limit:
        raise SystemExit(f"Backup enthält mehr als {entry_limit} ZIP-Einträge")
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
        if total_uncompressed > uncompressed_limit:
            raise SystemExit(f"Backup überschreitet entpackt das Größenlimit von {uncompressed_limit} Bytes")
        if item.file_size and item.file_size / max(item.compress_size, 1) > compression_ratio_limit:
            raise SystemExit(f"ZIP-Eintrag überschreitet das Kompressionslimit: {item.filename}")
    for item in entries:
        relative = safe_relative_path(item.filename.rstrip("/"), "ZIP-Pfad")
        normalized = relative.as_posix()
        # Client caches are restored selectively from the authenticated .bbm via
        # the WebUI. A bare-metal Manager restore must not copy multi-GiB client
        # cache tar streams into the persistent Manager data directory.
        if normalized.startswith("data/client-borg-cache/"):
            continue
        archive.extract(item, destination)

permissions_path = destination / "permissions.json"
if permissions_path.is_file():
    try:
        permissions = json.loads(permissions_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("permissions.json ist ungültig") from exc
    if not isinstance(permissions, dict) or len(permissions) > (max_cache_entries if include_cache else max_entries):
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

def sqlite_quick_check(path: Path, label: str):
    if not path.is_file():
        raise SystemExit(f"{label} fehlt im Manager-Backup")
    try:
        with sqlite3.connect(path, timeout=60) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise SystemExit(f"{label} kann nicht gelesen werden") from exc
    if not result or str(result[0]).casefold() != "ok":
        raise SystemExit(f"{label} ist beschädigt")

manager_database = destination / "data" / "manager.db"
security_database = destination / "data" / "security" / "security.db"
master_key_path = destination / "data" / "security" / "master.key"
sqlite_quick_check(manager_database, "Manager-Datenbank")
sqlite_quick_check(security_database, "Security-Datenbank")
if not master_key_path.is_file():
    raise SystemExit("Master-Key fehlt im Manager-Backup")
try:
    cipher = Fernet(master_key_path.read_bytes().strip())
except (OSError, ValueError, TypeError) as exc:
    raise SystemExit("Master-Key im Manager-Backup ist ungültig") from exc
try:
    with sqlite3.connect(security_database, timeout=60) as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"users", "secrets"} - tables:
            raise SystemExit("Security-Datenbank im Manager-Backup ist unvollständig")
        if int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]) < 1:
            raise SystemExit("Security-Datenbank im Manager-Backup enthält kein Benutzerkonto")
        secret_rows = connection.execute("SELECT scope,name,encrypted_value FROM secrets").fetchall()
except sqlite3.Error as exc:
    raise SystemExit("Security-Datenbank im Manager-Backup konnte nicht vollständig geprüft werden") from exc
system_names = set()
for scope, name, encrypted_value in secret_rows:
    value = str(encrypted_value or "")
    if not value.startswith("v2:"):
        raise SystemExit(f"Geheimnis {scope}/{name} verwendet ein nicht unterstütztes Format")
    try:
        cipher.decrypt(value[3:].encode("ascii"))
    except (InvalidToken, UnicodeEncodeError, ValueError) as exc:
        raise SystemExit(f"Geheimnis {scope}/{name} kann mit dem gesicherten Master-Key nicht entschlüsselt werden") from exc
    if str(scope) == "system":
        system_names.add(str(name))
required_identity = {
    "controller_private_key", "controller_public_key",
    "repository_ssh_host_private_key", "repository_ssh_host_public_key",
    "tls_certificate", "tls_private_key",
}
missing_identity = required_identity - system_names
if missing_identity:
    raise SystemExit("Manager-Backup enthält nicht alle SSH-/TLS-Identitäten: " + ", ".join(sorted(missing_identity)))
print(f"Backup v{manifest.get('app_version', '?')} vom {manifest.get('created_at', '?')} vollständig geprüft.")
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
prompt BBM_ARCHIVE_MOUNT_PATH "Host-Verzeichnis für schreibgeschützte Archiv-Mounts" "$(env_value BBM_ARCHIVE_MOUNT_PATH "$DEFAULT_ARCHIVE_MOUNT_PATH")"
prompt BBM_REPOSITORY_PUBLIC_HOST "Vom Client erreichbarer DNS-Name / IP des neuen Servers" "$(env_value BBM_REPOSITORY_PUBLIC_HOST "$(hostname -f 2>/dev/null || hostname)")"
prompt BBM_HTTPS_PORT "HTTPS-WebUI-Port" "$(env_value BBM_HTTPS_PORT 8443)"
prompt BBM_REPOSITORY_SSH_PORT "Repository-SSH-Port" "$(env_value BBM_REPOSITORY_SSH_PORT 2222)"

[[ "$BBM_DATA_PATH" == /* && "$BBM_REPOSITORY_PATH" == /* && "$BBM_ARCHIVE_MOUNT_PATH" == /* ]] || fail "Daten- und Repository-Pfad müssen absolut sein"
[[ "$BBM_DATA_PATH" != "$BBM_REPOSITORY_PATH" ]] || fail "Daten- und Repository-Pfad dürfen nicht identisch sein"
[[ "$BBM_DATA_PATH/" != "$BBM_REPOSITORY_PATH/"* ]] || fail "Das Manager-Datenverzeichnis darf nicht innerhalb des Repository-Verzeichnisses liegen"
RESTORE_TIMEZONE="$(env_value TZ "$DEFAULT_TIMEZONE")"
[[ -n "$RESTORE_TIMEZONE" && "$RESTORE_TIMEZONE" =~ ^[A-Za-z0-9_+./-]+$ && "$RESTORE_TIMEZONE" != /* && "$RESTORE_TIMEZONE" != *'..'* ]] \
  || fail "Zeitzone im Backup ist ungültig: $RESTORE_TIMEZONE"
mkdir -p -- "$BBM_DATA_PATH" "$BBM_REPOSITORY_PATH" "$BBM_ARCHIVE_MOUNT_PATH"
if find "$BBM_DATA_PATH" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  SAFETY_COPY="${BBM_DATA_PATH%/}-vor-restore-$(date +%Y%m%d-%H%M%S)"
  echo "Vorhandene Manager-Daten werden nach $SAFETY_COPY verschoben."
  mv -- "$BBM_DATA_PATH" "$SAFETY_COPY"
  mkdir -p -- "$BBM_DATA_PATH"
fi
cp -a -- "$TMP_DIR/data/." "$BBM_DATA_PATH/"

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
BBM_BACKUP_CACHE_MAX_FILE_BYTES=$(env_value BBM_BACKUP_CACHE_MAX_FILE_BYTES 34359738368)
BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES=$(env_value BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES 137438953472)
BBM_BACKUP_CACHE_MAX_ENTRIES=$(env_value BBM_BACKUP_CACHE_MAX_ENTRIES 250000)
BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO=$(env_value BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO 5000)
BBM_COMMAND_TIMEOUT=$(env_value BBM_COMMAND_TIMEOUT 86400)
BBM_APPEARANCE=$(env_value BBM_APPEARANCE auto)
BBM_REPOSITORY_SIZE_AFTER_RUN=$(env_value BBM_REPOSITORY_SIZE_AFTER_RUN 1)
BBM_REPOSITORY_PUBLIC_HOST=$BBM_REPOSITORY_PUBLIC_HOST
BBM_REPOSITORY_SSH_PORT=$BBM_REPOSITORY_SSH_PORT
BBM_DATA_PATH=$BBM_DATA_PATH
BBM_REPOSITORY_PATH=$BBM_REPOSITORY_PATH
BBM_ARCHIVE_MOUNT_PATH=$BBM_ARCHIVE_MOUNT_PATH
BBM_BORG_UID=$(env_value BBM_BORG_UID 1000)
BBM_BORG_GID=$(env_value BBM_BORG_GID 1000)
BBM_STORAGE_GUARD_ENABLED=$(env_value BBM_STORAGE_GUARD_ENABLED 1)
BBM_STORAGE_GUARD_THRESHOLD_PERCENT=$(env_value BBM_STORAGE_GUARD_THRESHOLD_PERCENT 95)
BBM_HEALTH_REQUIRE_SSHD=$(env_value BBM_HEALTH_REQUIRE_SSHD 1)
BBM_LOG_MAX_BYTES=$(env_value BBM_LOG_MAX_BYTES 10485760)
BBM_LOG_ROTATIONS=$(env_value BBM_LOG_ROTATIONS 5)
EOF
chmod 600 .env

echo "Manager-Daten wiederhergestellt. Installation wird mit Sicherheitsdatenbank und Master-Key abgeschlossen."
BBM_INSTALL_NONINTERACTIVE=1 bash install.sh
