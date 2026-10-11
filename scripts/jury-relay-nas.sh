#!/usr/bin/env bash
# Управление отдельным jury relay на NAS. Не настраивает VPS, DNS или роутер.
set -Eeuo pipefail
set +x
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
umask 077

readonly PROJECT_NAME=fspjury
readonly ENV_FILE=.env.jury
readonly VPS_HOST=80.87.198.60
readonly TUNNEL_USER=fspjury-tunnel
readonly CADDY_IMAGE='caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f'

die() {
  printf '%s\n' "$*" >&2
  exit 1
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

compose() {
  local individual
  individual="$(env_value FSP_JURY_INDIVIDUAL_REGISTRATION)"
  local -a overrides=(-f compose.yaml -f compose.jury.yaml -f compose.jury-relay.yaml)
  case "$individual" in
    1) overrides+=(-f compose.jury-public-demo.yaml -f compose.jury-individual.yaml) ;;
    ''|0) ;;
    *) die 'FSP_JURY_INDIVIDUAL_REGISTRATION должен быть 0 или 1.' ;;
  esac
  docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" \
    "${overrides[@]}" "$@"
}

require_relay_env() {
  [[ -f "$ENV_FILE" ]] || die "Нет $ENV_FILE. Сначала выполните ./scripts/jury.sh init."
  FSP_JURY_DOMAIN="$(env_value FSP_JURY_DOMAIN)"
  FSP_JURY_VPS_HOST="$(env_value FSP_JURY_VPS_HOST)"
  FSP_JURY_VPS_SSH_PORT="$(env_value FSP_JURY_VPS_SSH_PORT)"
  FSP_JURY_TUNNEL_USER="$(env_value FSP_JURY_TUNNEL_USER)"
  FSP_JURY_SSH_KEY_PATH="$(env_value FSP_JURY_SSH_KEY_PATH)"
  FSP_JURY_SSH_KNOWN_HOSTS_PATH="$(env_value FSP_JURY_SSH_KNOWN_HOSTS_PATH)"
  FSP_JURY_RELAY_ACTIVATE="$(env_value FSP_JURY_RELAY_ACTIVATE)"
  FSP_JURY_SUBNET="$(env_value FSP_JURY_SUBNET)"
  FSP_JURY_EDGE_IP="$(env_value FSP_JURY_EDGE_IP)"

  [[ "$FSP_JURY_DOMAIN" == 'fsptest.kolesnikovny.ru' ]] || die "Ожидается fsptest.kolesnikovny.ru."
  [[ "$FSP_JURY_VPS_HOST" == "$VPS_HOST" ]] || die "Relay закреплён за выбранным ru2 $VPS_HOST."
  [[ "${FSP_JURY_VPS_SSH_PORT:-22}" == '22' ]] || die "Для проверенной схемы ожидается SSH TCP 22."
  [[ "$FSP_JURY_TUNNEL_USER" == "$TUNNEL_USER" ]] || die "Ожидается отдельный пользователь $TUNNEL_USER."
  [[ "${FSP_JURY_SUBNET:-10.254.242.0/24}" == '10.254.242.0/24' ]] || \
    die "Relay Caddy закреплён за jury subnet 10.254.242.0/24."
  [[ "${FSP_JURY_EDGE_IP:-10.254.242.10}" == '10.254.242.10' ]] || \
    die "Relay Caddy закреплён за 10.254.242.10."
  [[ "$FSP_JURY_SSH_KEY_PATH" == /* && -f "$FSP_JURY_SSH_KEY_PATH" ]] || die "Нужен абсолютный путь к private key вне Git."
  [[ "$FSP_JURY_SSH_KNOWN_HOSTS_PATH" == /* && -s "$FSP_JURY_SSH_KNOWN_HOSTS_PATH" ]] || die "Нужен непустой pinned known_hosts вне Git."

  local key_mode
  key_mode="$(stat -c '%a' "$FSP_JURY_SSH_KEY_PATH")"
  [[ "$key_mode" == '400' || "$key_mode" == '600' ]] || die "Private key должен иметь режим 0400 или 0600, сейчас $key_mode."
  [[ "$(stat -c '%u' "$FSP_JURY_SSH_KEY_PATH")" == '10001' ]] || \
    die "Private key должен принадлежать UID 10001 контейнера tunnel."
}

config_summary() {
  require_relay_env
  compose config --quiet
  printf 'Relay: %s -> %s@%s:%s, VPS listen 127.0.0.1:18470, NAS listen 127.0.0.1:18083.\n' \
    "$FSP_JURY_DOMAIN" "$FSP_JURY_TUNNEL_USER" "$FSP_JURY_VPS_HOST" "${FSP_JURY_VPS_SSH_PORT:-22}"
  printf 'Ключи и пароли настроены локально; значения не выведены. Активация: %s.\n' \
    "${FSP_JURY_RELAY_ACTIVATE:-выключена}"
}

validate() {
  require_relay_env
  compose config --quiet
  local caddyfile="$PWD/docker/jury/Caddyfile.relay"
  if [[ "$(env_value FSP_JURY_INDIVIDUAL_REGISTRATION)" == '1' ]]; then
    caddyfile="$PWD/docker/jury/Caddyfile.public-demo"
  fi
  # Отдельная проверка без Compose-сети: не занимает фиксированный IP работающего edge.
  docker run --rm --network none --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges:true \
    --mount "type=bind,src=$caddyfile,dst=/etc/caddy/Caddyfile,readonly" \
    --env "FSP_JURY_BASIC_AUTH_USER=$(env_value FSP_JURY_BASIC_AUTH_USER)" \
    --env "FSP_JURY_BASIC_AUTH_HASH=$(env_value FSP_JURY_BASIC_AUTH_HASH)" \
    "$CADDY_IMAGE" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  compose build tunnel
}

gate() {
  require_relay_env
  [[ "$FSP_JURY_RELAY_ACTIVATE" == 'VPS_TLS_AND_TUNNEL_VERIFIED' ]] || \
    die "Relay закрыт: после VPS/TLS/SSH/DNS проверок задайте FSP_JURY_RELAY_ACTIVATE=VPS_TLS_AND_TUNNEL_VERIFIED."
  local resolved
  resolved="$(docker run --rm --network bridge --cap-drop ALL --security-opt no-new-privileges:true \
    "$CADDY_IMAGE" getent hosts "$FSP_JURY_DOMAIN" | awk '{print $1}')"
  grep -Fxq "$VPS_HOST" <<< "$resolved" || die "DNS A не указывает на выбранный VPS $VPS_HOST."
  compose config --quiet
  printf 'Relay gate пройден. Он не заменяет внешнюю HTTPS-проверку и проверку ограничений VPS SSH.\n'
}

case "${1:-help}" in
  config) config_summary ;;
  validate) validate ;;
  gate) gate ;;
  prepare)
    require_relay_env
    if [[ "$(env_value FSP_JURY_INDIVIDUAL_REGISTRATION)" == '1' ]]; then
      # Публичный edge не может запускаться обходным bootstrap-путём.
      gate
    fi
    validate
    compose up -d --build --wait --wait-timeout "${FSP_JURY_START_TIMEOUT:-900}" db app runner edge tunnel
    printf 'Relay подготовлен; индивидуальный публичный режим требует пройденного gate. NAS edge остаётся на loopback.\n'
    ;;
  start)
    gate
    validate
    compose up -d --build --wait --wait-timeout "${FSP_JURY_START_TIMEOUT:-900}" db app runner edge tunnel
    ;;
  status) require_relay_env; compose ps ;;
  logs) require_relay_env; compose logs --tail 100 edge app db tunnel ;;
  stop) require_relay_env; compose stop tunnel edge runner app db ;;
  reset)
    require_relay_env
    [[ "${2:-}" == '--yes' ]] || die "Удаление только fspjury требует: ./scripts/jury-relay-nas.sh reset --yes"
    compose down --volumes --remove-orphans
    ;;
  *)
    printf 'Использование: %s {config|validate|prepare|gate|start|status|logs|stop|reset --yes}\n' "$0" >&2
    exit 2
    ;;
esac
