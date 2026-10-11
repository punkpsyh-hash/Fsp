#!/usr/bin/env bash
# Отдельный временный HTTPS-стенд жюри; публичный запуск закрыт явным gate.
set -Eeuo pipefail
set +x
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
umask 077

readonly PROJECT_NAME=fspjury
readonly ENV_FILE=.env.jury
readonly CADDY_IMAGE='caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f'
readonly PYTHON_IMAGE='python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e'

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

random_secret() {
  docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true \
    "$PYTHON_IMAGE" python -c 'import secrets; print(secrets.token_urlsafe(48))'
}

compose() {
  docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" \
    -f compose.yaml -f compose.jury.yaml "$@"
}

env_value() {
  local key="$1" line value
  line="$(grep -m1 -E "^${key}=" "$ENV_FILE" || true)"
  [[ -n "$line" ]] || return 0
  value="${line#*=}"
  if [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

require_env() {
  [[ -f "$ENV_FILE" ]] || die "Нет $ENV_FILE. Сначала выполните ./scripts/jury.sh init."
  FSP_JURY_DOMAIN="$(env_value FSP_JURY_DOMAIN)"
  FSP_JURY_LAN_ADDRESS="$(env_value FSP_JURY_LAN_ADDRESS)"
  FSP_JURY_PUBLIC_IP="$(env_value FSP_JURY_PUBLIC_IP)"
  FSP_JURY_OPERATOR_NAME="$(env_value FSP_JURY_OPERATOR_NAME)"
  FSP_JURY_OPERATOR_CONTACT="$(env_value FSP_JURY_OPERATOR_CONTACT)"
  FSP_JURY_OPERATOR_CONFIRMED="$(env_value FSP_JURY_OPERATOR_CONFIRMED)"
  FSP_JURY_STORAGE_COUNTRY="$(env_value FSP_JURY_STORAGE_COUNTRY)"
  FSP_JURY_PASSWORD="$(env_value FSP_JURY_PASSWORD)"
  FSP_JURY_BASIC_AUTH_HASH="$(env_value FSP_JURY_BASIC_AUTH_HASH)"
  FSP_JURY_ACTIVATE="$(env_value FSP_JURY_ACTIVATE)"
  [[ "${FSP_JURY_DOMAIN:-}" == 'fsptest.kolesnikovny.ru' ]] || die "Ожидается согласованный домен fsptest.kolesnikovny.ru."
  [[ -n "${FSP_JURY_LAN_ADDRESS:-}" ]] || die "Не задан FSP_JURY_LAN_ADDRESS."
  [[ -n "${FSP_JURY_OPERATOR_NAME:-}" ]] || die "Не задан фактический оператор данных."
  [[ -n "${FSP_JURY_OPERATOR_CONTACT:-}" ]] || die "Не задан контакт оператора данных."
  [[ "$FSP_JURY_OPERATOR_CONTACT" == *@*.* && "$FSP_JURY_OPERATOR_CONTACT" != *.invalid ]] || die "Контакт оператора должен быть действительным email."
  [[ "${FSP_JURY_OPERATOR_CONFIRMED:-}" == '1' ]] || die "Фактический оператор и его email не подтверждены администратором."
  [[ "${FSP_JURY_STORAGE_COUNTRY:-}" == 'RU' ]] || die "Страна хранения должна быть подтверждена оператором как RU."
  [[ ${#FSP_JURY_PASSWORD} -ge 20 ]] || die "Пароль приложения должен содержать не менее 20 символов."
  [[ -n "${FSP_JURY_BASIC_AUTH_HASH:-}" ]] || die "Не задан hash edge-пароля."
}

init() {
  [[ ! -e "$ENV_FILE" ]] || die "$ENV_FILE уже существует; он не перезаписан."
  local domain lan operator contact operator_ack public_ip app_password edge_user edge_password edge_hash
  read -r -p 'Домен [fsptest.kolesnikovny.ru]: ' domain
  domain="${domain:-fsptest.kolesnikovny.ru}"
  [[ "$domain" == 'fsptest.kolesnikovny.ru' ]] || die "Для этого стенда согласован только fsptest.kolesnikovny.ru."
  read -r -p 'LAN-адрес NAS [192.168.1.58]: ' lan
  lan="${lan:-192.168.1.58}"
  [[ "$lan" =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]] || die "Нужен частный LAN IPv4 NAS."
  read -r -p 'Фактическое наименование оператора данных: ' operator
  [[ -n "$operator" && "$operator" != *\'* ]] || die "Оператор данных обязателен; одинарная кавычка не поддерживается в локальном env-файле."
  read -r -p 'Действительный публичный email оператора: ' contact
  [[ "$contact" == *@*.* && "$contact" != *.invalid ]] || die "Нужен действительный email оператора."
  printf 'Проверьте: оператор «%s», email «%s». Это фактический владелец временного стенда и адрес для обращений.\n' "$operator" "$contact"
  read -r -p 'Для подтверждения введите OPERATOR-CONFIRMED: ' operator_ack
  [[ "$operator_ack" == 'OPERATOR-CONFIRMED' ]] || die "Оператор не подтверждён; конфигурация не создана."
  read -r -p 'Подтверждённый публичный IPv4 (оставьте пустым до проверки): ' public_ip
  read -r -p 'Имя для внешнего Basic Auth [jury]: ' edge_user
  edge_user="${edge_user:-jury}"
  [[ "$edge_user" =~ ^[A-Za-z0-9._-]{3,64}$ ]] || die "Некорректное имя Basic Auth."

  app_password="$(random_secret)"
  edge_password="$(random_secret)"
  edge_hash="$(printf '%s\n' "$edge_password" | docker run --rm -i --network none --cap-drop ALL \
    --cap-add NET_BIND_SERVICE --security-opt no-new-privileges:true \
    "$CADDY_IMAGE" caddy hash-password --algorithm argon2id)"
  [[ "$edge_hash" == '$argon2id$'* ]] || die "Caddy не создал Argon2id hash."

  local db_password runner_token
  db_password="$(random_secret)"
  runner_token="$(random_secret)"
  {
    printf "FSP_DB_PASSWORD='%s'\n" "$db_password"
    printf "FSP_RUNNER_TOKEN='%s'\n" "$runner_token"
    printf "FSP_JURY_DOMAIN='%s'\n" "$domain"
    printf "FSP_JURY_LAN_ADDRESS='%s'\n" "$lan"
    printf "FSP_JURY_PUBLIC_IP='%s'\n" "$public_ip"
    printf "FSP_JURY_OPERATOR_NAME='%s'\n" "$operator"
    printf "FSP_JURY_OPERATOR_CONTACT='%s'\n" "$contact"
    printf "FSP_JURY_OPERATOR_CONFIRMED='1'\n"
    printf "FSP_JURY_STORAGE_COUNTRY='RU'\n"
    printf "FSP_JURY_PASSWORD='%s'\n" "$app_password"
    printf "FSP_JURY_BASIC_AUTH_USER='%s'\n" "$edge_user"
    printf "FSP_JURY_BASIC_AUTH_PASSWORD='%s'\n" "$edge_password"
    printf "FSP_JURY_BASIC_AUTH_HASH='%s'\n" "$edge_hash"
    printf "FSP_JURY_ACTIVATE=''\n"
  } > "$ENV_FILE"
  unset app_password edge_password edge_hash db_password runner_token
  printf '%s создан с правами текущего пользователя. Пароли сгенерированы автоматически и не выведены. Публичная активация оставлена выключенной.\n' "$ENV_FILE"
}

config_summary() {
  require_env
  compose config --quiet
  printf 'Домен: %s\nLAN NAS: %s\nПубличный IPv4: %s\nОператор: %s\nEmail оператора: %s\nХранение: %s\nАктивация: %s\n' \
    "$FSP_JURY_DOMAIN" "$FSP_JURY_LAN_ADDRESS" "${FSP_JURY_PUBLIC_IP:-не подтверждён}" \
    "$FSP_JURY_OPERATOR_NAME" "$FSP_JURY_OPERATOR_CONTACT" "$FSP_JURY_STORAGE_COUNTRY" \
    "${FSP_JURY_ACTIVATE:-выключена}"
  printf 'Секреты приложения и edge: настроены; значения скрыты. Полная Compose-конфигурация не выводилась.\n'
}

gate() {
  require_env
  [[ "${FSP_JURY_ACTIVATE:-}" == 'DNS_AND_ROUTER_VERIFIED' ]] || die "Публичная активация закрыта: после всех проверок задайте FSP_JURY_ACTIVATE=DNS_AND_ROUTER_VERIFIED."
  [[ "${FSP_JURY_PUBLIC_IP:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Не задан подтверждённый FSP_JURY_PUBLIC_IP."
  local resolved
  resolved="$(docker run --rm --network bridge --cap-drop ALL --cap-add NET_BIND_SERVICE \
    --security-opt no-new-privileges:true "$CADDY_IMAGE" getent hosts "$FSP_JURY_DOMAIN" | awk '{print $1}')"
  grep -Fxq "$FSP_JURY_PUBLIC_IP" <<< "$resolved" || die "DNS A не совпадает с подтверждённым публичным IPv4."
  compose config --quiet
  printf 'Локальный gate пройден. Он не доказывает внешний проброс, доступность 80/443 или статичность IP.\n'
}

validate() {
  require_env
  compose config --quiet
  compose run --rm -T --no-deps edge caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
}

case "${1:-help}" in
  init) init ;;
  config) config_summary ;;
  validate) validate ;;
  gate) gate ;;
  build) require_env; compose build app runner ;;
  start)
    gate
    validate
    compose up -d --build --wait --wait-timeout "${FSP_JURY_START_TIMEOUT:-900}" db app runner edge
    printf 'Стенд запущен локально на NAS; внешнюю доступность проверьте отдельно по docs/61-temporary-domain-stand.md.\n'
    ;;
  status) require_env; compose ps ;;
  logs) require_env; compose logs --tail 100 edge app db runner ;;
  stop) require_env; compose stop ;;
  reset)
    require_env
    [[ "${2:-}" == '--yes' ]] || die "Удаление только jury-контейнеров и jury-volumes требует: ./scripts/jury.sh reset --yes"
    compose down --volumes --remove-orphans
    ;;
  *)
    printf 'Использование: %s {init|config|validate|gate|build|start|status|logs|stop|reset --yes}\n' "$0" >&2
    exit 2
    ;;
esac
