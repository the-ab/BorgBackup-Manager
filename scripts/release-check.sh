#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

required_files=(
  LICENSE NOTICE SECURITY.md CONTRIBUTING.md THIRD-PARTY-NOTICES.md
  RELEASE_CHECKLIST.de.md RELEASE_CHECKLIST.md
  .gitignore .dockerignore VERSION app/release.py scripts/project-audit.py
  compose.yaml
  docker-compose/compose.yaml docker-compose/.env.example
  docker-compose/README.de.md docker-compose/README.md
)
for file in "${required_files[@]}"; do
  test -s "$file" || { echo "Missing required release file: $file" >&2; exit 1; }
done

for forbidden in .env docker-compose/.env install-config.env docker-compose.override.yml; do
  test ! -e "$forbidden" || { echo "Local-only file must not be released: $forbidden" >&2; exit 1; }
done

for runtime_directory in data repositories archive-mounts; do
  test ! -e "$runtime_directory" || { echo "Runtime directory must not be released: $runtime_directory" >&2; exit 1; }
done

if find . -path './.git' -prune -o -type f \
  \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.log' \
     -o -name '*.pem' -o -name '*.key' \) -print -quit | grep -q .; then
  echo "Potential runtime database, log or private key file found." >&2
  exit 1
fi

python scripts/project-audit.py
python -m compileall -q app tests scripts/project-audit.py

mapfile -t test_files < <(find tests -maxdepth 1 -type f -name 'test_*.py' -print | sort)
((${#test_files[@]} > 0)) || { echo "No test files found." >&2; exit 1; }
test_group_count=5
for ((group_index=0; group_index<test_group_count; group_index++)); do
  group_files=()
  for ((file_index=group_index; file_index<${#test_files[@]}; file_index+=test_group_count)); do
    group_files+=("${test_files[$file_index]}")
  done
  ((${#group_files[@]} > 0)) || continue
  if ((group_index == 3)); then
    # These filesystem/process-heavy tests are intentionally isolated because
    # their combined teardown can retain helper processes in constrained builders.
    for file_index in "${!group_files[@]}"; do
      test_file="${group_files[$file_index]}"
      echo "Running isolated $test_file ($((file_index + 1))/${#group_files[@]}) ..."
      timeout 180 pytest -q -o faulthandler_timeout=60 "$test_file"
    done
    continue
  fi
  echo "Running test group $((group_index + 1))/$test_group_count (${#group_files[@]} files) ..."
  timeout 300 pytest -q -o faulthandler_timeout=60 "${group_files[@]}"
done


node --check app/static/app.js
node --check app/static/i18n.js
node --check app/static/theme-init.js

bash -n install.sh update.sh recovery.sh restore-backup.sh scripts/release-check.sh
sh -n docker/entrypoint.sh docker/borg-serve.sh

echo "Release checks passed."
