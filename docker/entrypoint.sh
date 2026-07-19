#!/bin/sh
set -eu

borg_uid="${BBM_BORG_UID:-1000}"
borg_gid="${BBM_BORG_GID:-1000}"
case "$borg_uid:$borg_gid" in
  *[!0-9:]*|:*|*:) echo "Invalid BBM_BORG_UID or BBM_BORG_GID" >&2; exit 1 ;;
esac
if [ "$borg_uid" -eq 0 ] || [ "$borg_gid" -eq 0 ]; then
  echo "Borg repository UID and GID must be non-root" >&2
  exit 1
fi

groupmod -o -g "$borg_gid" borg
usermod -o -u "$borg_uid" -g "$borg_gid" borg

mkdir -p /data/repository-ssh /data/logs /data/exports /data/run-logs /data/archive-cache /data/security /data/borg-cache /data/borg-security /repositories /run/sshd /run/bbm-secrets
chmod 711 /data
chmod 700 /data/security /data/exports /data/run-logs /data/archive-cache /data/borg-cache /data/borg-security /run/bbm-secrets
chmod 711 /data/repository-ssh
chown borg:borg /data/logs /data/exports /data/borg-cache /data/borg-security
chmod 750 /data/logs
touch /data/logs/borg-serve.log /data/logs/sshd.log /data/repository-ssh/authorized_keys
chown borg:borg /data/logs/borg-serve.log /data/repository-ssh/authorized_keys
chown root:borg /data/logs/sshd.log
chmod 640 /data/logs/borg-serve.log /data/logs/sshd.log
chmod 600 /data/repository-ssh/authorized_keys

for access in r w x; do
  if ! runuser -u borg -- test "-$access" /repositories; then
    echo "Repository directory /repositories lacks -$access access for UID:GID ${borg_uid}:${borg_gid}." >&2
    echo "Correct the ownership/permissions of BBM_REPOSITORY_PATH on the Docker host." >&2
    exit 1
  fi
done

# Alte Installationen können einmalig Admin-Token und BBM_SECRET_KEY in der
# Host-.env enthalten. Die Werte werden nur zur Migration eingelesen.
legacy_env_file=/run/bbm-host.env
# v1.0.20 and older may still contain the historical default cookie name.
# app/config.py normalizes it for this process. Never rewrite this file from
# inside the container: it is a single-file Docker bind mount and atomic
# replacement tools such as `sed -i` fail with "Device or resource busy".
if [ -f "$legacy_env_file" ] && grep -qx 'BBM_SESSION_COOKIE_NAME=bbm_session' "$legacy_env_file"; then
  echo "Historical session cookie name detected; using bbm_session_v2 at runtime"
fi
read_legacy_value() {
  key="$1"
  [ -f "$legacy_env_file" ] || return 0
  sed -n "s/^${key}=//p" "$legacy_env_file" | tail -n 1
}
if [ -z "${BBM_ADMIN_TOKEN:-}" ]; then BBM_ADMIN_TOKEN=$(read_legacy_value BBM_ADMIN_TOKEN); fi
if [ -z "${BBM_SECRET_KEY:-}" ]; then BBM_SECRET_KEY=$(read_legacy_value BBM_SECRET_KEY); fi
export BBM_ADMIN_TOKEN BBM_SECRET_KEY

# Migriert alle Geheimnisse in /data/security/security.db und materialisiert
# ausschließlich die für die Containerlaufzeit erforderlichen Schlüssel unter
# /run/bbm-secrets. /run ist nicht persistent.
python -m app.security_bootstrap
# Prevent the unprivileged Web API from repeating the root-only runtime
# materialization during FastAPI startup.
export BBM_RUNTIME_SECURITY_PREPARED=1
mkdir -p /run/bbm-secrets/repository-keys

# The Web API does not require root privileges. Give the dedicated borg user
# access only to the persistent application state and the runtime material it
# actually consumes; keep the SSH host private key root-owned.
chown -R borg:borg /data
chmod 711 /data
chmod 700 /data/security /data/exports /data/run-logs /data/archive-cache /data/borg-cache /data/borg-security
chmod 750 /data/logs
chmod 711 /data/repository-ssh
chown root:borg /data/logs/sshd.log
chmod 640 /data/logs/borg-serve.log /data/logs/sshd.log
chmod 600 /data/repository-ssh/authorized_keys

chown root:borg /run/bbm-secrets
chmod 750 /run/bbm-secrets
chown -R borg:borg /run/bbm-secrets/tls /run/bbm-secrets/repository-keys
find /run/bbm-secrets/tls /run/bbm-secrets/repository-keys -type d -exec chmod 700 {} +
find /run/bbm-secrets/tls /run/bbm-secrets/repository-keys -type f -exec chmod 600 {} +
chown root:borg /run/bbm-secrets/repository-ssh
chmod 750 /run/bbm-secrets/repository-ssh
chown root:root /run/bbm-secrets/repository-ssh/ssh_host_ed25519_key
chmod 600 /run/bbm-secrets/repository-ssh/ssh_host_ed25519_key
chown root:borg /run/bbm-secrets/repository-ssh/ssh_host_ed25519_key.pub
chmod 640 /run/bbm-secrets/repository-ssh/ssh_host_ed25519_key.pub

if [ -f "$legacy_env_file" ] && { [ -n "${BBM_ADMIN_TOKEN:-}" ] || [ -n "${BBM_SECRET_KEY:-}" ]; }; then
  python - "$legacy_env_file" <<'PYSECURITYENV'
from pathlib import Path
import os, sys
path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
legacy = {"BBM_ADMIN_TOKEN", "BBM_SECRET_KEY", "BBM_ALLOW_LEGACY_TOKEN_AUTH"}
cleaned = [line for line in lines if line.split("=", 1)[0].strip() not in legacy]
with path.open("w", encoding="utf-8") as handle:
    handle.write("\n".join(cleaned).rstrip() + "\n")
    handle.flush(); os.fsync(handle.fileno())
try: path.chmod(0o600)
except OSError: pass
PYSECURITYENV
  echo "Legacy security values were migrated and removed from the host .env"
fi
unset BBM_ADMIN_TOKEN BBM_SECRET_KEY

rm -f /run/bbm-secrets/sshd-config.valid
/usr/sbin/sshd -t
printf 'ok\n' > /run/bbm-secrets/sshd-config.valid
chown root:borg /run/bbm-secrets/sshd-config.valid
chmod 640 /run/bbm-secrets/sshd-config.valid

sshd_pid=""
api_pid=""
stopping=0
stop_services() {
  [ "$stopping" -eq 0 ] || return 0
  stopping=1
  [ -z "$api_pid" ] || kill -TERM "$api_pid" 2>/dev/null || true
  [ -z "$sshd_pid" ] || kill -TERM "$sshd_pid" 2>/dev/null || true
  [ -z "$api_pid" ] || wait "$api_pid" 2>/dev/null || true
  [ -z "$sshd_pid" ] || wait "$sshd_pid" 2>/dev/null || true
}
trap 'stop_services; exit 143' TERM INT HUP
trap 'stop_services' EXIT

/usr/sbin/sshd -D -E /data/logs/sshd.log &
sshd_pid=$!

ready=0
i=0
while [ "$i" -lt 30 ]; do
  if ! kill -0 "$sshd_pid" 2>/dev/null; then
    echo "Repository sshd terminated during startup" >&2
    tail -n 100 /data/logs/sshd.log >&2 2>/dev/null || true
    exit 1
  fi
  if python - <<'PY' >/dev/null 2>&1
import socket
with socket.create_connection(("127.0.0.1", 2222), timeout=2) as connection:
    connection.settimeout(2)
    banner = b""
    while len(banner) < 255 and b"\n" not in banner:
        chunk = connection.recv(255 - len(banner))
        if not chunk: break
        banner += chunk
    if not banner.startswith(b"SSH-"):
        raise RuntimeError("invalid SSH banner")
PY
  then
    ready=1; break
  fi
  i=$((i + 1)); sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "Repository sshd did not open 127.0.0.1:2222" >&2
  exit 1
fi

runuser -u borg -- env HOME=/repositories \
  uvicorn app.main:app --host 0.0.0.0 --port 8443 \
  --ssl-certfile /run/bbm-secrets/tls/fullchain.pem \
  --ssl-keyfile /run/bbm-secrets/tls/privkey.pem --no-proxy-headers &
api_pid=$!

log_max_bytes="${BBM_LOG_MAX_BYTES:-10485760}"
log_rotations="${BBM_LOG_ROTATIONS:-5}"
case "$log_max_bytes:$log_rotations" in
  *[!0-9:]*|:*|*:) echo "Invalid BBM_LOG_MAX_BYTES or BBM_LOG_ROTATIONS" >&2; exit 1 ;;
esac
if [ "$log_max_bytes" -le 0 ]; then
  echo "BBM_LOG_MAX_BYTES must be greater than zero" >&2
  exit 1
fi
rotate_log() {
  file="$1"; [ "$log_rotations" -gt 0 ] || return 0; [ -f "$file" ] || return 0
  size=$(wc -c < "$file" 2>/dev/null || printf '0'); [ "$size" -ge "$log_max_bytes" ] || return 0
  i="$log_rotations"
  while [ "$i" -gt 1 ]; do previous=$((i - 1)); [ ! -f "$file.$previous" ] || mv -f "$file.$previous" "$file.$i"; i="$previous"; done
  cp -f "$file" "$file.1"; : > "$file"
}
last_log_rotation=0
while :; do
  if ! kill -0 "$sshd_pid" 2>/dev/null; then wait "$sshd_pid" 2>/dev/null || rc=$?; echo "Repository sshd stopped unexpectedly (rc=${rc:-0})" >&2; exit "${rc:-1}"; fi
  if ! kill -0 "$api_pid" 2>/dev/null; then wait "$api_pid" 2>/dev/null || rc=$?; echo "Web API stopped unexpectedly (rc=${rc:-0})" >&2; exit "${rc:-1}"; fi
  now=$(date +%s)
  if [ $((now - last_log_rotation)) -ge 300 ]; then rotate_log /data/logs/sshd.log; rotate_log /data/logs/borg-serve.log; last_log_rotation="$now"; fi
  sleep 2
done
