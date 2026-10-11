#!/usr/bin/env bash
# Архив только отслеживаемого кода HEAD; ни .env, ни база, ни локальные credentials.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  printf 'Сначала завершите и закоммитьте изменения: архив фиксирует только чистый HEAD.\n' >&2
  exit 1
fi
while IFS= read -r -d '' file; do
  case "$file" in
    .env.example|.env.*.example) ;;
    .env|.env.*|*/.env|*/.env.*|*.key|*.pem|*.p12|*.pfx|id_rsa*|id_ed25519*|*/id_rsa*|*/id_ed25519*|secrets/*|*/secrets/*|credentials/*|*/credentials/*|backups/*|*/backups/*|.git-credentials|*/.git-credentials|.netrc|*/.netrc)
      printf 'Архив остановлен: запрещённый отслеживаемый путь %s\n' "$file" >&2
      exit 1 ;;
  esac
done < <(git ls-tree -r --name-only -z HEAD)
commit="$(git rev-parse HEAD)"
mkdir -p docs/delivery
archive="docs/delivery/fsp-source-${commit}.zip"
temporary="$(mktemp 'docs/delivery/fsp-source-XXXXXXXX.zip')"
trap 'rm -f -- "$temporary"' EXIT
git archive --format=zip --prefix=Fsp/ --output="$temporary" HEAD
if [[ -e "$archive" ]]; then
  cmp -- "$temporary" "$archive"
else
  mv -- "$temporary" "$archive"
fi
printf 'Исходники коммита %s: %s\n' "$commit" "$archive"
sha256sum -- "$archive"
printf 'Архив предназначен для передачи жюри; передача и доступ получателя здесь не выполнены.\n'
