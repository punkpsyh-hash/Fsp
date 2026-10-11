#!/usr/bin/env bash
# Точечная подготовка ru2. Изменяет только отдельного SSH user/include и exact nginx vhost.
set -Eeuo pipefail
set +x
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

readonly DOMAIN=fsptest.kolesnikovny.ru
readonly VPS_IP=80.87.198.60
readonly TUNNEL_USER=fspjury-tunnel
readonly VHOST=/etc/nginx/sites-available/fsptest.kolesnikovny.ru.conf
readonly VHOST_LINK=/etc/nginx/sites-enabled/fsptest.kolesnikovny.ru.conf
readonly WEBROOT=/var/www/fsptest-acme
readonly SSHD_SNIPPET=/etc/ssh/sshd_config.d/70-fspjury-relay.conf
readonly LOGROTATE_SNIPPET=/etc/logrotate.d/fspjury-relay
readonly CERTBOT_IMAGE='certbot/certbot:v5.8.0@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20'
readonly MARKER=FSP_JURY_RELAY_V1

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "$(id -u)" == '0' ]] || die "Команда должна выполняться root на выбранном VPS."
  [[ "$(hostname -I | tr ' ' '\n' | grep -Fxc "$VPS_IP" || true)" -ge 1 ]] || \
    die "Этот script закреплён за ru2 $VPS_IP."
}

managed_or_absent() {
  [[ ! -e "$1" ]] || grep -Fq "$MARKER" "$1" || die "$1 существует и не принадлежит jury relay."
}

assert_ssh_ownership() {
  managed_or_absent "$SSHD_SNIPPET"
  if id "$TUNNEL_USER" >/dev/null 2>&1; then
    local account home auth
    account="$(getent passwd "$TUNNEL_USER")"
    home="$(cut -d: -f6 <<< "$account")"
    [[ "$home" == "/home/$TUNNEL_USER" ]] || die "Существующий $TUNNEL_USER имеет чужой home $home."
    auth="$home/.ssh/authorized_keys"
    [[ -f "$auth" && "$(wc -l < "$auth")" -eq 1 ]] || die "Существующий $TUNNEL_USER не имеет единственного managed authorized_keys."
    grep -Fq "$MARKER" "$auth" || die "Существующий $TUNNEL_USER не принадлежит jury relay."
    [[ -f "$SSHD_SNIPPET" ]] || die "Существующий $TUNNEL_USER найден без managed sshd snippet."
  else
    [[ ! -e "/home/$TUNNEL_USER" ]] || die "Home /home/$TUNNEL_USER существует без системного пользователя."
  fi
}

preflight() {
  require_root
  command -v nginx >/dev/null || die "nginx не установлен."
  command -v docker >/dev/null || die "Docker не установлен."
  command -v sshd >/dev/null || die "sshd не установлен."
  command -v logrotate >/dev/null || die "logrotate не установлен."
  nginx -t
  sshd -t
  managed_or_absent "$VHOST"
  managed_or_absent "$VHOST_LINK"
  managed_or_absent "$LOGROTATE_SNIPPET"
  assert_ssh_ownership
  if [[ ! -e "$VHOST" ]] && nginx -T 2>&1 | grep -Eq "server_name[[:space:]]+$DOMAIN([[:space:];])"; then
    die "Домен уже объявлен в другом nginx vhost."
  fi
  printf 'Preflight ru2 пройден; конфигурация не изменена.\n'
}

install_ssh() {
  require_root
  local public_key_file="${2:-}"
  assert_ssh_ownership
  [[ -f "$public_key_file" ]] || die "Укажите файл нового public key: install-ssh /path/id_ed25519.pub"
  [[ "$(wc -l < "$public_key_file")" -eq 1 ]] || die "Public key должен занимать ровно одну строку."
  local public_key_type public_key_blob
  read -r public_key_type public_key_blob _ < "$public_key_file"
  [[ "$public_key_type" == 'ssh-ed25519' && "$public_key_blob" =~ ^[A-Za-z0-9+/=]+$ ]] || \
    die "Разрешён только один Ed25519 public key."

  if ! id "$TUNNEL_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "/home/$TUNNEL_USER" --shell /usr/sbin/nologin "$TUNNEL_USER"
  fi
  # '*' является невозможным password hash без признака locked-account '!'.
  # Password/KbdInteractive одновременно запрещены в Match-блоке.
  usermod --password '*' "$TUNNEL_USER"
  install -d -m 0700 -o "$TUNNEL_USER" -g "$TUNNEL_USER" "/home/$TUNNEL_USER/.ssh"
  printf 'restrict,port-forwarding,permitlisten="127.0.0.1:18470" %s %s %s\n' \
    "$public_key_type" "$public_key_blob" "$MARKER" \
    > "/home/$TUNNEL_USER/.ssh/authorized_keys"
  chown "$TUNNEL_USER:$TUNNEL_USER" "/home/$TUNNEL_USER/.ssh/authorized_keys"
  chmod 0600 "/home/$TUNNEL_USER/.ssh/authorized_keys"
  local snippet_backup=''
  if [[ -f "$SSHD_SNIPPET" ]]; then
    snippet_backup="$(mktemp)"
    cp -a "$SSHD_SNIPPET" "$snippet_backup"
  fi
  install -m 0644 docker/jury/sshd-jury-relay.conf "$SSHD_SNIPPET"
  if ! sshd -t; then
    if [[ -n "$snippet_backup" ]]; then
      cp -a "$snippet_backup" "$SSHD_SNIPPET"
    else
      rm -f "$SSHD_SNIPPET"
    fi
    [[ -z "$snippet_backup" ]] || rm -f "$snippet_backup"
    die "sshd validation failed; предыдущий snippet восстановлен."
  fi
  [[ -z "$snippet_backup" ]] || rm -f "$snippet_backup"
  systemctl reload ssh
  printf 'SSH relay user установлен; private key не копировался на VPS.\n'
}

install_http() {
  require_root
  [[ ! -e "$VHOST" && ! -e "$VHOST_LINK" && ! -L "$VHOST_LINK" ]] || \
    die "Vhost или его symlink уже существует; HTTP stage не перезаписан."
  if nginx -T 2>&1 | grep -Eq "server_name[[:space:]]+$DOMAIN([[:space:];])"; then
    die "Домен уже объявлен в другом nginx vhost."
  fi
  install -d -m 0755 "$WEBROOT/.well-known/acme-challenge"
  logrotate --debug docker/jury/logrotate-nginx-vps.conf >/dev/null
  install -m 0644 docker/jury/logrotate-nginx-vps.conf "$LOGROTATE_SNIPPET"
  install -m 0644 docker/jury/nginx-vps-http.conf "$VHOST"
  ln -s "$VHOST" "$VHOST_LINK"
  if ! nginx -t; then
    rm -f "$VHOST_LINK" "$VHOST"
    rm -f "$LOGROTATE_SNIPPET"
    die "HTTP vhost отклонён nginx и удалён."
  fi
  systemctl reload nginx
}

certbot() {
  docker run --rm --network bridge --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --tmpfs /tmp:size=32m,mode=1777 \
    --volume /etc/letsencrypt:/etc/letsencrypt \
    --volume /var/lib/letsencrypt:/var/lib/letsencrypt \
    --volume "$WEBROOT:$WEBROOT" \
    "$CERTBOT_IMAGE" "$@" \
    --config-dir /etc/letsencrypt --work-dir /var/lib/letsencrypt \
    --logs-dir /var/lib/letsencrypt/log
}

issue_cert() {
  require_root
  [[ -f "$VHOST" ]] && grep -Fq "$MARKER" "$VHOST" || die "Сначала установите HTTP stage."
  [[ "$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | grep -Fxc "$VPS_IP" || true)" -ge 1 ]] || \
    die "DNS A ещё не указывает на $VPS_IP."
  local probe="jury-$(date +%s)-$$"
  printf '%s' "$probe" > "$WEBROOT/.well-known/acme-challenge/$probe"
  chmod 0644 "$WEBROOT/.well-known/acme-challenge/$probe"
  [[ "$(curl -fsS --max-time 10 "http://$DOMAIN/.well-known/acme-challenge/$probe")" == "$probe" ]] || \
    die "ACME webroot недоступен снаружи."
  rm -f "$WEBROOT/.well-known/acme-challenge/$probe"
  certbot certonly --webroot --webroot-path "$WEBROOT" --domain "$DOMAIN" \
    --agree-tos --register-unsafely-without-email --non-interactive
}

install_https() {
  require_root
  [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" && -f "/etc/letsencrypt/live/$DOMAIN/privkey.pem" ]] || \
    die "Сертификат $DOMAIN отсутствует."
  [[ -f "$VHOST" ]] && grep -Fq "$MARKER" "$VHOST" || die "Vhost не принадлежит jury relay."
  cp -a "$VHOST" "$VHOST.before-https"
  install -m 0644 docker/jury/nginx-vps.conf "$VHOST"
  if ! nginx -t; then
    mv -f "$VHOST.before-https" "$VHOST"
    die "HTTPS vhost отклонён nginx; HTTP stage восстановлен."
  fi
  rm -f "$VHOST.before-https"
  systemctl reload nginx
}

renew_cert() {
  require_root
  local flags=()
  if [[ "${2:-}" == '--dry-run' ]]; then
    flags+=(--dry-run)
  elif [[ -n "${2:-}" ]]; then
    die "Для проверки продления допустим только renew --dry-run."
  fi
  certbot renew --cert-name "$DOMAIN" --webroot --webroot-path "$WEBROOT" "${flags[@]}"
  nginx -t
  systemctl reload nginx
}

reconfigure_cert() {
  require_root
  certbot reconfigure --cert-name "$DOMAIN" --webroot --webroot-path "$WEBROOT" --non-interactive
}

status() {
  require_root
  nginx -t
  sshd -t
  ss -ltnH '( sport = :18470 )' || true
  [[ -f "$VHOST" ]] && grep -F "$MARKER" "$VHOST" >/dev/null
  printf 'Read-only status завершён. Проверяйте, что 18470 слушает только 127.0.0.1.\n'
}

case "${1:-help}" in
  preflight) preflight ;;
  install-ssh) install_ssh "$@" ;;
  install-http) install_http ;;
  issue-cert) issue_cert ;;
  install-https) install_https ;;
  renew) renew_cert "$@" ;;
  reconfigure-cert) reconfigure_cert ;;
  status) status ;;
  *)
    printf 'Использование: %s {preflight|install-ssh PUBLIC_KEY|install-http|issue-cert|install-https|renew [--dry-run]|reconfigure-cert|status}\n' "$0" >&2
    exit 2
    ;;
esac
