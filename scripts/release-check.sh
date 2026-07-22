#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

required_files=(
  LICENSE NOTICE SECURITY.md CONTRIBUTING.md THIRD-PARTY-NOTICES.md
  .gitignore .dockerignore VERSION app/release.py
)
for file in "${required_files[@]}"; do
  test -s "$file" || { echo "Missing required release file: $file" >&2; exit 1; }
done

for forbidden in .env install-config.env docker-compose.override.yml; do
  test ! -e "$forbidden" || { echo "Local-only file must not be released: $forbidden" >&2; exit 1; }
done

if find . -path './.git' -prune -o -type f \
  \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.log' \
     -o -name '*.pem' -o -name '*.key' \) -print -quit | grep -q .; then
  echo "Potential runtime database, log or private key file found." >&2
  exit 1
fi

python -m compileall -q app tests
python -m pytest -q

node --check app/static/app.js
node --check app/static/i18n.js
node --check app/static/theme-init.js

bash -n install.sh update.sh recovery.sh restore-backup.sh scripts/release-check.sh
sh -n docker/entrypoint.sh docker/borg-serve.sh

echo "Release checks passed."
