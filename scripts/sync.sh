#!/usr/bin/env bash
# Синхронизация рабочей копии; авторизация остаётся в настройках Git.
set -Eeuo pipefail
export GIT_TERMINAL_PROMPT=0
trap 'printf "Ошибка синхронизации (строка %s). Рабочие файлы не сбрасывались.\n" "$LINENO" >&2' ERR

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$project_dir"
git rev-parse --is-inside-work-tree >/dev/null

fail() { printf '%s\n' "$*" >&2; exit 1; }

load_branch() {
    branch="$(git symbolic-ref --quiet --short HEAD)" || fail 'HEAD отсоединён. Сначала выберите рабочую ветку; файлы сохранены.'
    remote="$(git config --get "branch.$branch.remote")" || fail 'Для ветки не настроен upstream. Настройте его явно перед синхронизацией.'
    merge_ref="$(git config --get "branch.$branch.merge")" || fail 'Для ветки не задана ветка upstream.'
    [[ "$remote" == origin ]] || fail 'Upstream должен ссылаться на origin. Проверьте настройки ветки; они не изменены.'
    [[ "$merge_ref" == refs/heads/* ]] || fail 'Upstream должен быть обычной веткой refs/heads/.'
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" || fail 'Ссылка upstream недоступна. Проверьте настройки origin и ветки.'
}

compare_history() {
    read -r ahead behind < <(git rev-list --left-right --count "HEAD...$upstream")
    if (( ahead > 0 && behind > 0 )); then
        fail "Ветки разошлись: локальных коммитов $ahead, удалённых $behind. Автоматическое объединение запрещено. Согласуйте merge/rebase вручную после проверки истории; данные сохранены."
    fi
}

case "${1:-status}" in
    status)
        git status --short --branch
        printf '\nУдалённые репозитории (credentials скрыты):\n'
        git remote -v | sed -E 's#(https?://)[^/[:space:]]*@#\1[redacted]@#g; s#\?[^[:space:]]*#?[redacted]#g'
        printf '\nТекущий HEAD origin на GitHub:\n'
        git ls-remote --exit-code origin HEAD
        printf '\nUpstream (по последнему fetch):\n'
        git for-each-ref --format='%(refname:short) %(upstream:short) %(upstream:track)' "$(git symbolic-ref --quiet HEAD || true)"
        ;;
    pull)
        [[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail 'Рабочая копия содержит изменения или новые файлы. Сохраните их сами; pull не выполнен.'
        load_branch
        git fetch origin
        compare_history
        git pull --ff-only --no-rebase origin "${merge_ref#refs/heads/}"
        ;;
    push)
        [[ -z "$(git ls-tree -r --name-only HEAD -- .github/workflows)" ]] || fail 'Push запрещён: коммит содержит GitHub CI/CD в .github/workflows. Сохраните конфигурацию локально и исключите её из Git; история и файлы не сбрасывались.'
        load_branch
        git fetch origin
        compare_history
        (( behind == 0 )) || fail "На origin есть $behind новых коммитов. Сначала выполните pull при чистой рабочей копии; локальные коммиты сохранены."
        git push origin "HEAD:$merge_ref"
        ;;
    *)
        printf 'Использование: %s {status|pull|push}\n' "$0" >&2
        exit 2
        ;;
esac
