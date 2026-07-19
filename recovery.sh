#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
SERVICE="borg-manager"
DC=()

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }

detect_compose() {
    local prefix=()
    command -v docker >/dev/null 2>&1 || die "Docker wurde nicht gefunden."
    if docker info >/dev/null 2>&1; then
        prefix=()
    elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
        prefix=(sudo)
    else
        die "Docker-Daemon ist nicht erreichbar."
    fi
    if "${prefix[@]}" docker compose version >/dev/null 2>&1; then
        DC=("${prefix[@]}" docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        DC=("${prefix[@]}" docker-compose)
    else
        die "Docker Compose wurde nicht gefunden."
    fi
}

compose() {
    "${DC[@]}" "$@"
}

require_environment() {
    detect_compose
    compose config --quiet >/dev/null 2>&1 || die "Keine gültige Compose-Konfiguration im Projektordner gefunden: $PROJECT_DIR"
    if ! compose ps --status running --services 2>/dev/null | grep -Fxq "$SERVICE"; then
        die "Der Dienst $SERVICE läuft nicht. Starte ihn zuerst mit: docker compose up -d"
    fi
}

run_module() {
    compose exec -T "$SERVICE" python -m "$@"
}

read_username() {
    local prompt="${1:-Benutzername}"
    local username
    read -r -p "$prompt: " username
    [[ -n "$username" ]] || die "Benutzername darf nicht leer sein."
    printf '%s' "$username"
}

confirm() {
    local prompt="$1"
    local answer
    read -r -p "$prompt [j/N]: " answer
    [[ "$answer" =~ ^[JjYy]$ ]]
}

show_menu() {
    cat <<'EOF'

BorgBackup Manager – Recovery
================================
1) Kontozustand anzeigen
2) Einmalige Erstanmeldedaten anzeigen
3) Benutzerkonto entsperren
4) Benutzerpasswort zurücksetzen
5) Benutzerpasswort zurücksetzen und Administratorrolle setzen
6) JSON-Status für Diagnose ausgeben
0) Beenden
EOF
}

status() { run_module app.account_recovery status; }
initial_admin() { run_module app.initial_admin; }
unlock() {
    local username="${1:-}"
    [[ -n "$username" ]] || username="$(read_username)"
    run_module app.account_recovery unlock "$username"
}
reset_account() {
    local username="${1:-}"
    local make_admin="${2:-false}"
    [[ -n "$username" ]] || username="$(read_username)"
    if ! confirm "Temporäres Passwort für '$username' erzeugen und alle Sitzungen widerrufen?"; then
        log "Abgebrochen."
        return 0
    fi
    if [[ "$make_admin" == "true" ]]; then
        run_module app.account_recovery reset "$username" --admin
    else
        run_module app.account_recovery reset "$username"
    fi
}

usage() {
    cat <<'EOF'
Verwendung:
  ./recovery.sh                       Interaktives Menü
  ./recovery.sh status                Kontostatus anzeigen
  ./recovery.sh status-json           JSON-Status anzeigen
  ./recovery.sh initial-admin         Einmalige Erstanmeldedaten anzeigen
  ./recovery.sh unlock BENUTZER       Konto entsperren
  ./recovery.sh reset BENUTZER        Passwort zurücksetzen
  ./recovery.sh reset-admin BENUTZER  Passwort zurücksetzen und Adminrolle setzen
EOF
}

main() {
    case "${1:-menu}" in
        -h|--help|help) usage; return 0 ;;
    esac
    require_environment
    case "${1:-menu}" in
        status) status ;;
        status-json) run_module app.account_recovery status --json ;;
        initial-admin) initial_admin ;;
        unlock) [[ $# -eq 2 ]] || die "Benutzername fehlt."; unlock "$2" ;;
        reset) [[ $# -eq 2 ]] || die "Benutzername fehlt."; reset_account "$2" false ;;
        reset-admin) [[ $# -eq 2 ]] || die "Benutzername fehlt."; reset_account "$2" true ;;
        menu)
            while true; do
                show_menu
                read -r -p "Auswahl: " choice
                case "$choice" in
                    1) status ;;
                    2) initial_admin ;;
                    3) unlock ;;
                    4) reset_account "" false ;;
                    5) reset_account "" true ;;
                    6) run_module app.account_recovery status --json ;;
                    0) exit 0 ;;
                    *) printf 'Ungültige Auswahl.\n' >&2 ;;
                esac
            done
            ;;
        *) usage; exit 2 ;;
    esac
}

main "$@"
