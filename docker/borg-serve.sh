#!/bin/sh
set -u

log_file=/data/logs/borg-serve.log
log_line() { printf '%s\n' "$*" 2>/dev/null >> "$log_file" || true; }
fail() {
  rc="$1"; shift
  log_line "$(date -u +%Y-%m-%dT%H:%M:%SZ) error rc=$rc $*"
  printf '%s\n' "$*" >&2
  exit "$rc"
}

repository=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repository)
      [ "$#" -ge 2 ] || fail 120 "Missing value for --repository"
      repository="$2"
      shift 2
      ;;
    *) fail 121 "Unsupported borg-serve wrapper argument: $1" ;;
  esac
done

[ -n "$repository" ] || fail 122 "No repository restriction was supplied"
case "$repository" in
  /repositories/*) ;;
  *) fail 123 "Repository restriction is outside /repositories" ;;
esac
case "$repository" in
  *'/../'*|*/..|*'/./'*|*/.) fail 124 "Repository restriction contains an unsafe path segment" ;;
esac

borg_version="$(/usr/bin/borg --version 2>&1 || true)"
log_line "$(date -u +%Y-%m-%dT%H:%M:%SZ) start uid=$(id -u) gid=$(id -g) peer=${SSH_CONNECTION:-unknown} repository=$repository command=${SSH_ORIGINAL_COMMAND:-none} borg=$borg_version"

[ -x /usr/bin/borg ] || fail 111 "Borg executable /usr/bin/borg is missing or not executable"
[ -d "$repository" ] || fail 112 "Managed repository directory does not exist: $repository"
[ -r "$repository" ] || fail 113 "Managed repository is not readable: $repository"
[ -w "$repository" ] || fail 114 "Managed repository is not writable: $repository"
[ -x "$repository" ] || fail 115 "Managed repository is not searchable: $repository"

/usr/bin/borg serve --restrict-to-repository "$repository"
rc=$?
log_line "$(date -u +%Y-%m-%dT%H:%M:%SZ) exit rc=$rc repository=$repository command=${SSH_ORIGINAL_COMMAND:-none}"
exit "$rc"
