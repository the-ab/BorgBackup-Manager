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

archive_mounts_enabled="${BBM_ARCHIVE_MOUNTS_ENABLED:-1}"
archive_mount_root="${BBM_ARCHIVE_MOUNT_ROOT:-/archive-mounts}"
case "$archive_mounts_enabled" in
  0|1) ;;
  *) echo "BBM_ARCHIVE_MOUNTS_ENABLED must be 0 or 1" >&2; exit 1 ;;
esac
case "$archive_mount_root" in
  /*) ;;
  *) echo "BBM_ARCHIVE_MOUNT_ROOT must be an absolute path" >&2; exit 1 ;;
esac

groupmod -o -g "$borg_gid" borg
usermod -o -u "$borg_uid" -g "$borg_gid" borg

mkdir -p /data/repository-ssh /data/logs /data/exports /data/run-logs /data/archive-cache /data/security /data/borg-cache /data/borg-security /repositories /run/sshd /run/bbm-secrets
if [ "$archive_mounts_enabled" = "1" ]; then
  mkdir -p "$archive_mount_root"
fi
chmod 711 /data
chmod 700 /data/security /data/exports /data/run-logs /data/archive-cache /data/borg-cache /data/borg-security /run/bbm-secrets
chmod 711 /data/repository-ssh
chown borg:borg /data/logs /data/exports /data/borg-cache /data/borg-security
chmod 750 /data/logs
touch /data/logs/borg-serve.log /data/logs/sshd.log /data/logs/debug.log /data/repository-ssh/authorized_keys
chown borg:borg /data/logs/borg-serve.log /data/logs/debug.log /data/repository-ssh/authorized_keys
chown root:borg /data/logs/sshd.log
chmod 640 /data/logs/borg-serve.log /data/logs/sshd.log /data/logs/debug.log
chmod 600 /data/repository-ssh/authorized_keys

repository_access_ok() {
  for access in r w x; do
    runuser -u borg -- test "-$access" /repositories || return 1
  done
}

# A directory created automatically by Docker for a fresh bind mount normally
# belongs to root. Initialize only an empty mount root; existing repository data
# is never changed recursively or silently. ACLs and already-correct group
# permissions remain untouched when the borg user already has full access.
if ! repository_access_ok; then
  repository_entry=""
  repository_scan_ok=0
  if repository_entry="$(find /repositories -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)"; then
    repository_scan_ok=1
  fi
  if [ "$repository_scan_ok" -eq 1 ] && [ -z "$repository_entry" ]; then
    echo "[borgbackup-manager] Initializing empty repository directory /repositories for UID:GID ${borg_uid}:${borg_gid}."
    if ! chown "${borg_uid}:${borg_gid}" /repositories || ! chmod u+rwx /repositories; then
      echo "[borgbackup-manager] Automatic initialization of /repositories failed." >&2
    fi
  elif [ "$repository_scan_ok" -eq 1 ]; then
    echo "[borgbackup-manager] Repository directory /repositories contains existing data; automatic recursive ownership changes are disabled." >&2
  else
    echo "[borgbackup-manager] Repository directory /repositories could not be inspected for safe first-start initialization." >&2
  fi
fi

for access in r w x; do
  if ! runuser -u borg -- test "-$access" /repositories; then
    echo "Repository directory /repositories lacks -$access access for UID:GID ${borg_uid}:${borg_gid}." >&2
    echo "Correct the ownership/permissions or ACLs of BBM_REPOSITORY_PATH on the Docker host." >&2
    exit 1
  fi
done

archive_mount_access_ok() {
  [ -d "$archive_mount_root" ] && [ ! -L "$archive_mount_root" ] || return 1
  for access in r w x; do
    runuser -u borg -- test "-$access" "$archive_mount_root" || return 1
  done
}

if [ "$archive_mounts_enabled" = "1" ]; then
  if ! archive_mount_access_ok; then
    archive_mount_entry=""
    archive_mount_scan_ok=0
    if archive_mount_entry="$(find "$archive_mount_root" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)"; then
      archive_mount_scan_ok=1
    fi
    if [ "$archive_mount_scan_ok" -eq 1 ] && [ -z "$archive_mount_entry" ]; then
      echo "[borgbackup-manager] Initializing empty archive mount directory $archive_mount_root for UID:GID ${borg_uid}:${borg_gid}."
      chown "${borg_uid}:${borg_gid}" "$archive_mount_root" || true
      chmod u+rwx "$archive_mount_root" || true
    elif [ "$archive_mount_scan_ok" -eq 1 ]; then
      echo "[borgbackup-manager] Archive mount directory $archive_mount_root contains existing data; recursive ownership changes are disabled." >&2
    else
      echo "[borgbackup-manager] Archive mount directory $archive_mount_root could not be inspected safely." >&2
    fi
  fi
  if ! archive_mount_access_ok; then
    echo "Archive mount directory $archive_mount_root lacks r/w/x access for UID:GID ${borg_uid}:${borg_gid}." >&2
    echo "Correct the ownership/permissions or ACLs of BBM_ARCHIVE_MOUNT_PATH on the Docker host." >&2
    exit 1
  fi
  [ -e /dev/fuse ] || { echo "/dev/fuse is required when archive mounts are enabled" >&2; exit 1; }
  command -v fusermount3 >/dev/null 2>&1 || command -v fusermount >/dev/null 2>&1 || {
    echo "fusermount3/fusermount is required when archive mounts are enabled" >&2; exit 1;
  }
  grep -Eq '^[[:space:]]*user_allow_other([[:space:]]*(#.*)?)?$' /etc/fuse.conf || {
    echo "/etc/fuse.conf must contain user_allow_other when archive mounts are enabled" >&2; exit 1;
  }
fi

# Initialize the current security store and materialize only the runtime keys
# required under /run/bbm-secrets. /run is not persistent.
python -m app.security_bootstrap

show_initial_admin_on_start="${BBM_SHOW_INITIAL_ADMIN_ON_START:-0}"
case "$show_initial_admin_on_start" in
  0|1) ;;
  *) echo "BBM_SHOW_INITIAL_ADMIN_ON_START must be 0 or 1" >&2; exit 1 ;;
esac
if [ "$show_initial_admin_on_start" = "1" ]; then
  echo "[borgbackup-manager] Checking for one-time administrator credentials."
  python -m app.initial_admin --announce-once
fi

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
chmod 640 /data/logs/borg-serve.log /data/logs/sshd.log /data/logs/debug.log
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

rm -f /run/bbm-secrets/sshd-config.valid
/usr/sbin/sshd -t
printf 'ok\n' > /run/bbm-secrets/sshd-config.valid
chown root:borg /run/bbm-secrets/sshd-config.valid
chmod 640 /run/bbm-secrets/sshd-config.valid

sshd_pid=""
api_pid=""
stopping=0
archive_mount_points() {
  python - "$archive_mount_root" <<'PYARCHIVEMOUNTS'
from pathlib import Path
import sys
root = Path(sys.argv[1])
def decode(value: str) -> str:
    return value.replace(r"\040", " ").replace(r"\011", "\t").replace(r"\012", "\n").replace(r"\134", "\\")
rows = []
try:
    lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8", errors="replace").splitlines()
except OSError:
    lines = []
for line in lines:
    before, sep, after = line.partition(" - ")
    if not sep:
        continue
    fields = before.split(); tail = after.split()
    if len(fields) < 5 or not tail or not tail[0].startswith("fuse"):
        continue
    path = Path(decode(fields[4]))
    if path == root or root in path.parents:
        rows.append(path)
for path in sorted(set(rows), key=lambda item: (len(item.parts), str(item)), reverse=True):
    print(path)
PYARCHIVEMOUNTS
}
cleanup_archive_mounts() {
  [ "$archive_mounts_enabled" = "1" ] || return 0
  archive_mount_points | while IFS= read -r mount_path; do
    [ -n "$mount_path" ] || continue
    echo "[borgbackup-manager] Unmounting archive mount $mount_path."
    timeout -k 1 5 runuser -u borg -- fusermount3 -u "$mount_path" 2>/dev/null \
      || timeout -k 1 5 runuser -u borg -- borg umount "$mount_path" 2>/dev/null \
      || timeout -k 1 5 runuser -u borg -- fusermount3 -uz "$mount_path" 2>/dev/null \
      || timeout -k 1 5 umount -l "$mount_path" 2>/dev/null \
      || echo "[borgbackup-manager] Archive mount could not be unmounted cleanly: $mount_path" >&2
  done
}
stop_services() {
  [ "$stopping" -eq 0 ] || return 0
  stopping=1
  [ -z "$api_pid" ] || kill -TERM "$api_pid" 2>/dev/null || true
  [ -z "$api_pid" ] || wait "$api_pid" 2>/dev/null || true
  cleanup_archive_mounts
  [ -z "$sshd_pid" ] || kill -TERM "$sshd_pid" 2>/dev/null || true
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

if [ "$archive_mounts_enabled" = "1" ]; then
  setpriv --reuid="$borg_uid" --regid="$borg_gid" --clear-groups \
    --inh-caps=+sys_admin --ambient-caps=+sys_admin \
    env HOME=/repositories \
    uvicorn app.main:app --host 0.0.0.0 --port 8443 \
    --ssl-certfile /run/bbm-secrets/tls/fullchain.pem \
    --ssl-keyfile /run/bbm-secrets/tls/privkey.pem --no-proxy-headers &
else
  runuser -u borg -- env HOME=/repositories \
    uvicorn app.main:app --host 0.0.0.0 --port 8443 \
    --ssl-certfile /run/bbm-secrets/tls/fullchain.pem \
    --ssl-keyfile /run/bbm-secrets/tls/privkey.pem --no-proxy-headers &
fi
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
  if [ $((now - last_log_rotation)) -ge 300 ]; then rotate_log /data/logs/sshd.log; rotate_log /data/logs/borg-serve.log; rotate_log /data/logs/debug.log; last_log_rotation="$now"; fi
  sleep 2
done
