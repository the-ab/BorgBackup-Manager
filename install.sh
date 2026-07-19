#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
umask 077
PROJECT_VERSION="$(cat VERSION 2>/dev/null || echo unbekannt)"
DEFAULT_BASE_PATH="/docker_data/borgbackup-manager"
DEFAULT_DATA_PATH="$DEFAULT_BASE_PATH/data"
DEFAULT_REPOSITORY_PATH="$DEFAULT_BASE_PATH/repositories"
DEFAULT_TIMEZONE="Europe/Berlin"
ROOT_PREFIX=()
DOCKER_PREFIX=()
ready=0

CONFIG_ONLY=0
if [[ "${1:-}" == "--config-only" ]]; then
  CONFIG_ONLY=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: bash install.sh [--config-only]" >&2
  exit 2
fi

say() { printf '\n%s\n' "$*"; }
fail() { echo "Fehler: $*" >&2; exit 1; }

read_existing() {
  local key="$1"
  [[ -f .env ]] || return 0
  sed -n "s/^${key}=//p" .env | tail -n 1
}

prompt() {
  local variable="$1" label="$2" default="$3" value=""
  if [[ "${BBM_INSTALL_NONINTERACTIVE:-0}" == "1" ]]; then
    value="${!variable:-$default}"
  else
    read -r -p "$label [$default]: " value
    value="${value:-$default}"
  fi
  printf -v "$variable" '%s' "$value"
}

absolute_directory() {
  local value="$1" label="$2"
  [[ "$value" == /* ]] || fail "$label muss ein absoluter Linux-Pfad sein: $value"
  [[ "$value" != *'$'* && "$value" != *'#'* && "$value" != *$'\n'* ]] \
    || fail "$label darf keine Dollarzeichen, # oder Zeilenumbrüche enthalten"
  mkdir -p -- "$value" || fail "$label kann nicht erstellt werden: $value"
  (cd -- "$value" && pwd -P)
}

validate_port() {
  local value="$1" label="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || ((value < 1 || value > 65535)); then
    fail "$label muss zwischen 1 und 65535 liegen"
  fi
}

validate_positive_integer() {
  local value="$1" label="$2" allow_zero="${3:-0}"
  [[ "$value" =~ ^[0-9]+$ ]] || fail "$label muss eine ganze Zahl sein"
  if [[ "$allow_zero" == "1" ]]; then
    ((value >= 0)) || fail "$label darf nicht negativ sein"
  else
    ((value > 0)) || fail "$label muss größer als 0 sein"
  fi
}

validate_boolean() {
  local value="$1" label="$2"
  [[ "$value" =~ ^[01]$ ]] || fail "$label muss 1 oder 0 sein"
}

validate_cookie_name() {
  local value="$1" label="$2"
  [[ "$value" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "$label enthält ungültige Zeichen"
}

validate_timezone() {
  local value="$1"
  [[ -n "$value" && "$value" =~ ^[A-Za-z0-9_+./-]+$ && "$value" != /* && "$value" != *'..'* ]] \
    || fail "Zeitzone ist ungültig: $value"
}

say "BorgBackup Manager v$PROJECT_VERSION – geführte Installation"
echo "Das Skript erzeugt die Konfiguration, richtet persistente Pfade ein und startet den Container."

existing_data="$(read_existing BBM_DATA_PATH)"
existing_repositories="$(read_existing BBM_REPOSITORY_PATH)"
existing_host="$(read_existing BBM_REPOSITORY_PUBLIC_HOST)"
existing_https_port="$(read_existing BBM_HTTPS_PORT)"
if [[ -z "$existing_https_port" ]]; then existing_https_port="$(read_existing BBM_HTTP_PORT)"; fi
existing_repo_port="$(read_existing BBM_REPOSITORY_SSH_PORT)"
existing_guard_enabled="$(read_existing BBM_STORAGE_GUARD_ENABLED)"
existing_guard_threshold="$(read_existing BBM_STORAGE_GUARD_THRESHOLD_PERCENT)"
existing_tls_hosts="$(read_existing BBM_TLS_HOSTS)"
existing_session_ttl="$(read_existing BBM_SESSION_TTL_SECONDS)"
existing_session_idle="$(read_existing BBM_SESSION_IDLE_TIMEOUT_SECONDS)"
existing_session_cookie="$(read_existing BBM_SESSION_COOKIE_NAME)"
existing_session_cookie_secure="$(read_existing BBM_SESSION_COOKIE_SECURE)"
existing_trusted_proxy_cidrs="$(read_existing BBM_TRUSTED_PROXY_CIDRS)"
existing_login_rate_window="$(read_existing BBM_LOGIN_RATE_WINDOW_SECONDS)"
existing_login_rate_block="$(read_existing BBM_LOGIN_RATE_BLOCK_SECONDS)"
existing_login_rate_ip="$(read_existing BBM_LOGIN_RATE_MAX_PER_IP)"
existing_login_rate_pair="$(read_existing BBM_LOGIN_RATE_MAX_PER_IP_USER)"
existing_security_retention="$(read_existing BBM_SECURITY_EVENT_RETENTION_DAYS)"
existing_security_rows="$(read_existing BBM_SECURITY_EVENT_MAX_ROWS)"
existing_backup_file_limit="$(read_existing BBM_BACKUP_MAX_FILE_BYTES)"
existing_backup_uncompressed_limit="$(read_existing BBM_BACKUP_MAX_UNCOMPRESSED_BYTES)"
existing_backup_entries="$(read_existing BBM_BACKUP_MAX_ENTRIES)"
existing_backup_ratio="$(read_existing BBM_BACKUP_MAX_COMPRESSION_RATIO)"
existing_command_timeout="$(read_existing BBM_COMMAND_TIMEOUT)"
existing_size_after_run="$(read_existing BBM_REPOSITORY_SIZE_AFTER_RUN)"
existing_appearance="$(read_existing BBM_APPEARANCE)"
existing_health_require_sshd="$(read_existing BBM_HEALTH_REQUIRE_SSHD)"
existing_log_max_bytes="$(read_existing BBM_LOG_MAX_BYTES)"
existing_log_rotations="$(read_existing BBM_LOG_ROTATIONS)"
existing_timezone="$(read_existing TZ)"
timezone="${TZ:-${existing_timezone:-$DEFAULT_TIMEZONE}}"

prompt BBM_DATA_PATH \
  "Host-Verzeichnis für Datenbank, Protokolle und SSH-Schlüssel" \
  "${existing_data:-$DEFAULT_DATA_PATH}"
prompt BBM_REPOSITORY_PATH \
  "Host-Verzeichnis für Borg-Repositories (darf ein vorhandener NFS-Mount sein)" \
  "${existing_repositories:-$DEFAULT_REPOSITORY_PATH}"
prompt BBM_REPOSITORY_PUBLIC_HOST \
  "DNS-Name oder IP des Docker-Hosts, erreichbar von den Backup-Geräten" \
  "${existing_host:-$(hostname -f 2>/dev/null || hostname)}"
prompt BBM_HTTPS_PORT "HTTPS-WebUI-Port" "${existing_https_port:-8443}"
prompt BBM_REPOSITORY_SSH_PORT "Borg-Repository-SSH-Port" "${existing_repo_port:-2222}"
prompt BBM_STORAGE_GUARD_ENABLED "Backups bei kritischer Speicherbelegung sperren (1/0)" "${existing_guard_enabled:-1}"
prompt BBM_STORAGE_GUARD_THRESHOLD_PERCENT "Speicher-Sperrgrenze in Prozent" "${existing_guard_threshold:-95}"

# Erweiterte Werte werden bei einer erneuten Konfiguration beibehalten. Sie
# lassen sich bei Bedarf anschließend direkt in .env ändern.
BBM_TLS_HOSTS="${BBM_TLS_HOSTS:-${existing_tls_hosts:-$BBM_REPOSITORY_PUBLIC_HOST,localhost,127.0.0.1}}"
BBM_SESSION_TTL_SECONDS="${BBM_SESSION_TTL_SECONDS:-${existing_session_ttl:-86400}}"
BBM_SESSION_IDLE_TIMEOUT_SECONDS="${BBM_SESSION_IDLE_TIMEOUT_SECONDS:-${existing_session_idle:-3600}}"
BBM_SESSION_COOKIE_NAME="${BBM_SESSION_COOKIE_NAME:-${existing_session_cookie:-bbm_session_v2}}"
BBM_SESSION_COOKIE_SECURE="${BBM_SESSION_COOKIE_SECURE:-${existing_session_cookie_secure:-always}}"
BBM_TRUSTED_PROXY_CIDRS="${BBM_TRUSTED_PROXY_CIDRS:-${existing_trusted_proxy_cidrs:-127.0.0.1/32,::1/128}}"
BBM_LOGIN_RATE_WINDOW_SECONDS="${BBM_LOGIN_RATE_WINDOW_SECONDS:-${existing_login_rate_window:-300}}"
BBM_LOGIN_RATE_BLOCK_SECONDS="${BBM_LOGIN_RATE_BLOCK_SECONDS:-${existing_login_rate_block:-900}}"
BBM_LOGIN_RATE_MAX_PER_IP="${BBM_LOGIN_RATE_MAX_PER_IP:-${existing_login_rate_ip:-20}}"
BBM_LOGIN_RATE_MAX_PER_IP_USER="${BBM_LOGIN_RATE_MAX_PER_IP_USER:-${existing_login_rate_pair:-5}}"
BBM_SECURITY_EVENT_RETENTION_DAYS="${BBM_SECURITY_EVENT_RETENTION_DAYS:-${existing_security_retention:-90}}"
BBM_SECURITY_EVENT_MAX_ROWS="${BBM_SECURITY_EVENT_MAX_ROWS:-${existing_security_rows:-10000}}"
BBM_BACKUP_MAX_FILE_BYTES="${BBM_BACKUP_MAX_FILE_BYTES:-${existing_backup_file_limit:-268435456}}"
BBM_BACKUP_MAX_UNCOMPRESSED_BYTES="${BBM_BACKUP_MAX_UNCOMPRESSED_BYTES:-${existing_backup_uncompressed_limit:-1073741824}}"
BBM_BACKUP_MAX_ENTRIES="${BBM_BACKUP_MAX_ENTRIES:-${existing_backup_entries:-5000}}"
BBM_BACKUP_MAX_COMPRESSION_RATIO="${BBM_BACKUP_MAX_COMPRESSION_RATIO:-${existing_backup_ratio:-250}}"
BBM_COMMAND_TIMEOUT="${BBM_COMMAND_TIMEOUT:-${existing_command_timeout:-86400}}"
BBM_REPOSITORY_SIZE_AFTER_RUN="${BBM_REPOSITORY_SIZE_AFTER_RUN:-${existing_size_after_run:-1}}"
BBM_APPEARANCE="${BBM_APPEARANCE:-${existing_appearance:-auto}}"
BBM_HEALTH_REQUIRE_SSHD="${BBM_HEALTH_REQUIRE_SSHD:-${existing_health_require_sshd:-1}}"
BBM_LOG_MAX_BYTES="${BBM_LOG_MAX_BYTES:-${existing_log_max_bytes:-10485760}}"
BBM_LOG_ROTATIONS="${BBM_LOG_ROTATIONS:-${existing_log_rotations:-5}}"

[[ "$BBM_REPOSITORY_PUBLIC_HOST" != *[[:space:]/]* \
   && "$BBM_REPOSITORY_PUBLIC_HOST" != *'$'* \
   && "$BBM_REPOSITORY_PUBLIC_HOST" != *'#'* \
   && "$BBM_REPOSITORY_PUBLIC_HOST" != *'='* \
   && -n "$BBM_REPOSITORY_PUBLIC_HOST" ]] \
  || fail "Repository-Host enthält ungültige Zeichen"
validate_port "$BBM_HTTPS_PORT" "HTTPS-WebUI-Port"
validate_port "$BBM_REPOSITORY_SSH_PORT" "Repository-SSH-Port"
validate_boolean "$BBM_STORAGE_GUARD_ENABLED" "Speicherplatz-Sperre"
if [[ ! "$BBM_STORAGE_GUARD_THRESHOLD_PERCENT" =~ ^[0-9]+$ ]] \
  || ((BBM_STORAGE_GUARD_THRESHOLD_PERCENT < 1 || BBM_STORAGE_GUARD_THRESHOLD_PERCENT > 100)); then
  fail "Speicher-Sperrgrenze muss zwischen 1 und 100 liegen"
fi
validate_positive_integer "$BBM_SESSION_TTL_SECONDS" "Sitzungsdauer"
validate_positive_integer "$BBM_SESSION_IDLE_TIMEOUT_SECONDS" "Sitzungs-Inaktivitätsgrenze"
((BBM_SESSION_IDLE_TIMEOUT_SECONDS <= BBM_SESSION_TTL_SECONDS)) || fail "Sitzungs-Inaktivitätsgrenze darf die absolute Sitzungsdauer nicht überschreiten"
for security_number in BBM_LOGIN_RATE_WINDOW_SECONDS BBM_LOGIN_RATE_BLOCK_SECONDS BBM_LOGIN_RATE_MAX_PER_IP BBM_LOGIN_RATE_MAX_PER_IP_USER BBM_SECURITY_EVENT_RETENTION_DAYS BBM_SECURITY_EVENT_MAX_ROWS BBM_BACKUP_MAX_FILE_BYTES BBM_BACKUP_MAX_UNCOMPRESSED_BYTES BBM_BACKUP_MAX_ENTRIES BBM_BACKUP_MAX_COMPRESSION_RATIO; do
  validate_positive_integer "${!security_number}" "$security_number"
done
python3 - "$BBM_TRUSTED_PROXY_CIDRS" <<'PYPROXY' || fail "BBM_TRUSTED_PROXY_CIDRS enthält ein ungültiges IP-Netz"
import ipaddress, sys
for value in sys.argv[1].split(','):
    if value.strip(): ipaddress.ip_network(value.strip(), strict=False)
PYPROXY
validate_positive_integer "$BBM_COMMAND_TIMEOUT" "Befehls-Timeout"
validate_boolean "$BBM_REPOSITORY_SIZE_AFTER_RUN" "Automatische Repository-Größenberechnung"
validate_boolean "$BBM_HEALTH_REQUIRE_SSHD" "SSH-Healthcheck"
validate_positive_integer "$BBM_LOG_MAX_BYTES" "Maximale Protokollgröße"
validate_positive_integer "$BBM_LOG_ROTATIONS" "Anzahl Protokollrotationen" 1
validate_cookie_name "$BBM_SESSION_COOKIE_NAME" "Sitzungs-Cookie-Name"
[[ "$BBM_SESSION_COOKIE_SECURE" =~ ^(auto|always|never)$ ]] || fail "Sitzungs-Cookie-Sicherheit muss auto, always oder never sein"
[[ "$BBM_APPEARANCE" =~ ^(auto|light|dark)$ ]] || fail "Darstellung muss auto, light oder dark sein"
[[ -n "$BBM_TLS_HOSTS" \
   && "$BBM_TLS_HOSTS" != *[[:space:]]* \
   && "$BBM_TLS_HOSTS" != *$'\n'* \
   && "$BBM_TLS_HOSTS" != *'$'* \
   && "$BBM_TLS_HOSTS" != *'#'* \
   && "$BBM_TLS_HOSTS" != *'='* ]] \
  || fail "TLS-Hostliste ist ungültig"
validate_timezone "$timezone"

BBM_DATA_PATH="$(absolute_directory "$BBM_DATA_PATH" "Datenverzeichnis")"
BBM_REPOSITORY_PATH="$(absolute_directory "$BBM_REPOSITORY_PATH" "Repository-Verzeichnis")"
[[ "$BBM_DATA_PATH" != "$BBM_REPOSITORY_PATH" ]] \
  || fail "Daten- und Repository-Verzeichnis dürfen nicht identisch sein"
[[ "$BBM_DATA_PATH/" != "$BBM_REPOSITORY_PATH/"* ]] \
  || fail "Das Manager-Datenverzeichnis darf nicht innerhalb des Repository-Verzeichnisses liegen"
mkdir -p -- "$BBM_DATA_PATH/repository-ssh" "$BBM_DATA_PATH/exports" "$BBM_DATA_PATH/security"
mkdir -p -- "$PROJECT_DIR/updates"

repo_owner_uid="$(stat -c '%u' "$BBM_REPOSITORY_PATH")"
repo_owner_gid="$(stat -c '%g' "$BBM_REPOSITORY_PATH")"
default_uid="$repo_owner_uid"
default_gid="$repo_owner_gid"
if [[ "$default_uid" == "0" ]]; then default_uid="${SUDO_UID:-1000}"; fi
if [[ "$default_gid" == "0" ]]; then default_gid="${SUDO_GID:-1000}"; fi
prompt BBM_BORG_UID "UID für den eingeschränkten Borg-Benutzer" "$default_uid"
prompt BBM_BORG_GID "GID für den eingeschränkten Borg-Benutzer" "$default_gid"
[[ "$BBM_BORG_UID" =~ ^[0-9]+$ && "$BBM_BORG_UID" != "0" ]] || fail "Borg-UID muss numerisch und ungleich 0 sein"
[[ "$BBM_BORG_GID" =~ ^[0-9]+$ && "$BBM_BORG_GID" != "0" ]] || fail "Borg-GID muss numerisch und ungleich 0 sein"
if [[ "$repo_owner_uid:$repo_owner_gid" != "$BBM_BORG_UID:$BBM_BORG_GID" ]]; then
  echo "Repository-Verzeichnis wird auf UID:GID $BBM_BORG_UID:$BBM_BORG_GID gesetzt."
  if [[ "$(id -u)" == "0" ]]; then
    chown "$BBM_BORG_UID:$BBM_BORG_GID" "$BBM_REPOSITORY_PATH" \
      || fail "Eigentümer konnte nicht gesetzt werden; NFS-Exportberechtigungen prüfen"
  elif command -v sudo >/dev/null 2>&1; then
    sudo chown "$BBM_BORG_UID:$BBM_BORG_GID" "$BBM_REPOSITORY_PATH" \
      || fail "Eigentümer konnte nicht gesetzt werden; NFS-Exportberechtigungen prüfen"
  else
    fail "Eigentümer des Repository-Verzeichnisses kann ohne sudo nicht gesetzt werden"
  fi
fi

legacy_admin_token="$(read_existing BBM_ADMIN_TOKEN)"
legacy_secret_key="$(read_existing BBM_SECRET_KEY)"

env_tmp="$(mktemp "$PROJECT_DIR/.env.XXXXXX")"
trap 'rm -f -- "$env_tmp"' EXIT
cat >"$env_tmp" <<EOF
TZ=$timezone
BBM_HTTPS_PORT=$BBM_HTTPS_PORT
BBM_REPOSITORY_SSH_PORT=$BBM_REPOSITORY_SSH_PORT
BBM_REPOSITORY_PUBLIC_HOST=$BBM_REPOSITORY_PUBLIC_HOST
BBM_TLS_HOSTS=$BBM_TLS_HOSTS
BBM_DATA_PATH=$BBM_DATA_PATH
BBM_REPOSITORY_PATH=$BBM_REPOSITORY_PATH
BBM_BORG_UID=$BBM_BORG_UID
BBM_BORG_GID=$BBM_BORG_GID
BBM_SESSION_TTL_SECONDS=$BBM_SESSION_TTL_SECONDS
BBM_SESSION_IDLE_TIMEOUT_SECONDS=$BBM_SESSION_IDLE_TIMEOUT_SECONDS
BBM_SESSION_COOKIE_NAME=$BBM_SESSION_COOKIE_NAME
BBM_SESSION_COOKIE_SECURE=$BBM_SESSION_COOKIE_SECURE
BBM_TRUSTED_PROXY_CIDRS=$BBM_TRUSTED_PROXY_CIDRS
BBM_LOGIN_RATE_WINDOW_SECONDS=$BBM_LOGIN_RATE_WINDOW_SECONDS
BBM_LOGIN_RATE_BLOCK_SECONDS=$BBM_LOGIN_RATE_BLOCK_SECONDS
BBM_LOGIN_RATE_MAX_PER_IP=$BBM_LOGIN_RATE_MAX_PER_IP
BBM_LOGIN_RATE_MAX_PER_IP_USER=$BBM_LOGIN_RATE_MAX_PER_IP_USER
BBM_SECURITY_EVENT_RETENTION_DAYS=$BBM_SECURITY_EVENT_RETENTION_DAYS
BBM_SECURITY_EVENT_MAX_ROWS=$BBM_SECURITY_EVENT_MAX_ROWS
BBM_BACKUP_MAX_FILE_BYTES=$BBM_BACKUP_MAX_FILE_BYTES
BBM_BACKUP_MAX_UNCOMPRESSED_BYTES=$BBM_BACKUP_MAX_UNCOMPRESSED_BYTES
BBM_BACKUP_MAX_ENTRIES=$BBM_BACKUP_MAX_ENTRIES
BBM_BACKUP_MAX_COMPRESSION_RATIO=$BBM_BACKUP_MAX_COMPRESSION_RATIO
BBM_COMMAND_TIMEOUT=$BBM_COMMAND_TIMEOUT
BBM_APPEARANCE=$BBM_APPEARANCE
BBM_REPOSITORY_SIZE_AFTER_RUN=$BBM_REPOSITORY_SIZE_AFTER_RUN
BBM_STORAGE_GUARD_ENABLED=$BBM_STORAGE_GUARD_ENABLED
BBM_STORAGE_GUARD_THRESHOLD_PERCENT=$BBM_STORAGE_GUARD_THRESHOLD_PERCENT
BBM_HEALTH_REQUIRE_SSHD=$BBM_HEALTH_REQUIRE_SSHD
BBM_LOG_MAX_BYTES=$BBM_LOG_MAX_BYTES
BBM_LOG_ROTATIONS=$BBM_LOG_ROTATIONS
EOF
# Bei einer Migration aus 0.8.x werden die bisherigen Werte genau für den
# einmaligen Start übernommen. Die Anwendung legt danach Benutzer, Sitzungen
# und den Master-Key unter /data/security an; neue Installationen benötigen
# diese Variablen nicht mehr.
if [[ -n "$legacy_admin_token" ]]; then printf 'BBM_ADMIN_TOKEN=%s\n' "$legacy_admin_token" >> "$env_tmp"; fi
if [[ -n "$legacy_secret_key" ]]; then printf 'BBM_SECRET_KEY=%s\n' "$legacy_secret_key" >> "$env_tmp"; fi

# Unbekannte/erweiterte Schlüssel einer vorhandenen .env bleiben erhalten.
# Veraltete Migrationsschalter werden bewusst nicht erneut übernommen.
if [[ -f .env ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ "$key" != "BBM_HTTP_PORT" && "$key" != "BBM_ALLOW_LEGACY_TOKEN_AUTH" ]] || continue
    grep -qE "^${key}=" "$env_tmp" || printf '%s\n' "$line" >> "$env_tmp"
  done < .env
fi
mv -f -- "$env_tmp" .env
trap - EXIT
chmod 600 .env

say "Konfiguration erstellt"
printf 'Daten:        %s\nRepositories: %s\nWebUI:        https://%s:%s\n' \
  "$BBM_DATA_PATH" "$BBM_REPOSITORY_PATH" "$BBM_REPOSITORY_PUBLIC_HOST" "$BBM_HTTPS_PORT"

if ((CONFIG_ONLY)); then
  echo "--config-only: Docker-Build wurde übersprungen."
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  if [[ "${BBM_INSTALL_NONINTERACTIVE:-0}" == "1" ]]; then
    fail "Docker fehlt. Installiere Docker Engine mit Compose-Plugin und starte das Skript erneut."
  fi
  read -r -p "Docker wurde nicht gefunden. Auf Debian/Ubuntu automatisch installieren? [j/N]: " install_docker
  if [[ "$install_docker" =~ ^[jJyY]$ ]]; then
    command -v apt-get >/dev/null 2>&1 || fail "Automatische Docker-Installation unterstützt nur apt-basierte Systeme"
    if [[ "$(id -u)" == "0" ]]; then
      ROOT_PREFIX=()
    elif command -v sudo >/dev/null 2>&1; then
      ROOT_PREFIX=(sudo)
    else
      fail "Docker-Installation benötigt root oder sudo"
    fi
    "${ROOT_PREFIX[@]}" apt-get update
    if ! "${ROOT_PREFIX[@]}" apt-get install -y docker.io docker-compose-v2; then
      "${ROOT_PREFIX[@]}" apt-get install -y docker.io docker-compose-plugin
    fi
    "${ROOT_PREFIX[@]}" systemctl enable --now docker
  else
    fail "Docker Engine mit Compose-Plugin wird benötigt"
  fi
fi

if docker info >/dev/null 2>&1; then
  DOCKER_PREFIX=()
elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
  DOCKER_PREFIX=(sudo)
else
  fail "Docker-Daemon ist nicht erreichbar. Starte Docker oder korrigiere die Benutzerberechtigung."
fi

dc() { "${DOCKER_PREFIX[@]}" docker compose "$@"; }
dc version >/dev/null 2>&1 || fail "Docker Compose v2 ist nicht verfügbar"

say "Container wird gebaut und gestartet"
dc config --quiet
dc build --pull
dc up -d

for _ in {1..40}; do
  if dc exec -T borg-manager python -c \
    "import ssl, urllib.request; urllib.request.urlopen('https://127.0.0.1:8443/api/ready', context=ssl._create_unverified_context(), timeout=2)" \
    >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready:-0}" != "1" ]]; then
  dc logs --tail=100 borg-manager
  fail "Der Dienst wurde nicht rechtzeitig bereit"
fi

say "Installation erfolgreich"
echo "WebUI: https://$BBM_REPOSITORY_PUBLIC_HOST:$BBM_HTTPS_PORT"
echo "Beim ersten Aufruf muss das automatisch erzeugte Zertifikat einmalig im Browser bestätigt werden."
echo
echo "Diesen öffentlichen Controller-Schlüssel einmalig auf jedem Backup-Gerät autorisieren:"
dc exec -T borg-manager python -c "from app.vault import get_system_secret; print(get_system_secret('controller_public_key') or 'Controller-Schlüssel fehlt')"
echo
echo "Danach das Gerät in der WebUI hinzufügen, SSH-Fingerprint prüfen und 'Repository-Zugang einrichten' wählen."
echo
echo "Updates: Release-ZIP nach $PROJECT_DIR/updates kopieren und 'bash update.sh' ausführen."


say "Anmeldung"
if dc exec -T borg-manager python -m app.initial_admin; then
  echo "Das einmalige Passwort liegt verschlüsselt in security.db und wird nach dem ersten Passwortwechsel entfernt."
else
  echo "Vorhandene Benutzerverwaltung wurde übernommen."
fi
