"""Имитация ФСП ID: OIDC-вход (authorization code + PKCE S256) и демо-реестр достижений.

Это локальный mock, а не интеграция: реального API, структуры данных и боевого Keycloak
организаторы не предоставляют (ТЗ §2, §4). Протокол повторяет публичный OIDC (discovery,
authorize, token, PKCE), поэтому замена mock на настоящий клиент ФСП ID меняет только
адреса и источник событий. Подтверждение достижений даёт реестр, а не кандидат.

Сигнал для ранжирования (10% балла) считается по событиям реестра:
* очки за результат: победитель 1.0, призёр 0.7, финалист 0.4, участник 0.15;
* командное событие ×0.8: вклад участника внутри команды честно не выделить;
* убывающий вес событий 1, 0.6, 0.36, ...: нельзя набрать профиль одними явками;
* дисциплины и уровень соревнований не ранжируются между собой (по Q&A);
* давность не учитывается (архива за годы нет); итог min(1, сумма / 1.5).
"""
import base64
from datetime import timedelta
import hashlib
import hmac
import secrets
from urllib.parse import urlencode
from html import escape

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import FspFlow, Profile, now

CLIENT_ID = 'fsp-career-demo'
FLOW_TTL = timedelta(minutes=10)
RESULT_POINTS = {'winner': 1.0, 'prize': 0.7, 'finalist': 0.4, 'participant': 0.15}
SATURATION = 1.5

# Синтетический реестр. Пароль — только для демонстрации входа жюри.
REGISTRY = {
    'FSP-1001': {'password': 'demo-1001', 'events': [
        {'event': 'Синтетический чемпионат · алгоритмы', 'discipline': 'Алгоритмы', 'kind': 'individual',
         'result': 'winner', 'place': 1, 'date': '2026-06-10'},
        {'event': 'Синтетический кубок · командный тур', 'discipline': 'Алгоритмы', 'kind': 'team',
         'result': 'prize', 'place': 3, 'date': '2026-03-12'}]},
    'FSP-1002': {'password': 'demo-1002', 'events': [
        {'event': 'Синтетический онлайн-отбор', 'discipline': 'Алгоритмы', 'kind': 'individual',
         'result': 'participant', 'place': 87, 'date': '2026-02-01'},
        {'event': 'Синтетический хакатон', 'discipline': 'Продуктовая разработка', 'kind': 'team',
         'result': 'participant', 'place': 21, 'date': '2026-04-18'},
        {'event': 'Синтетическая открытая олимпиада', 'discipline': 'Алгоритмы', 'kind': 'individual',
         'result': 'participant', 'place': 54, 'date': '2026-05-22'}]},
    'FSP-1003': {'password': 'demo-1003', 'events': []},
    'FSP-1004': {'password': 'demo-1004', 'events': [
        {'event': 'Синтетическое первенство · ИБ', 'discipline': 'Информационная безопасность', 'kind': 'individual',
         'result': 'finalist', 'place': 8, 'date': '2026-05-03'}]},
    'FSP-1005': {'password': 'demo-1005', 'events': [
        {'event': 'Синтетический чемпионат · робототехника', 'discipline': 'Робототехника', 'kind': 'team',
         'result': 'winner', 'place': 1, 'date': '2026-06-28'}]},
}


def events_for(member_id):
    registry = REGISTRY.get(member_id)
    return None if registry is None else [{**e, 'role': 'Участник команды' if e['kind'] == 'team' else 'Личный зачёт',
                                           'source': 'local-mock', 'demo': True} for e in registry['events']]


def signal_for(events):
    points = sorted((RESULT_POINTS[e['result']] * (0.8 if e['kind'] == 'team' else 1.0) for e in events), reverse=True)
    return round(min(1.0, sum(p * 0.6 ** i for i, p in enumerate(points)) / SATURATION), 3)


def check_password(member_id, password):
    registry = REGISTRY.get(member_id)
    expected = registry['password'] if registry else 'x' * 12   # сопоставимое время для неизвестного ID
    return hmac.compare_digest(password.encode(), expected.encode()) and registry is not None


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def challenge_for(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def discovery(issuer):
    return {'issuer': issuer, 'authorization_endpoint': issuer + '/authorize', 'token_endpoint': issuer + '/token',
            'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code'],
            'code_challenge_methods_supported': ['S256'], 'scopes_supported': ['openid', 'fsp.achievements'],
            'subject_types_supported': ['public'], 'mock': True}


def start(db, user_id, issuer, redirect_uri):
    """Создаёт запрос входа и возвращает адрес authorize."""
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    db.add(FspFlow(state=state, user_id=user_id, verifier=verifier, challenge=challenge_for(verifier)))
    db.commit()
    query = urlencode({'response_type': 'code', 'client_id': CLIENT_ID, 'redirect_uri': redirect_uri, 'scope': 'openid fsp.achievements',
                       'state': state, 'code_challenge': challenge_for(verifier), 'code_challenge_method': 'S256'})
    return issuer + '/authorize?' + query


def _flow(db, state):
    flow = db.get(FspFlow, state)
    if flow is None or flow.used or now() - _aware(flow.created_at) > FLOW_TTL:
        return None
    return flow


def _aware(value):
    from datetime import timezone
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def authorize_page(params, error=''):
    """Форма входа без встроенных стилей и скриптов (CSP). Параметры экранируются."""
    hidden = ''.join(f'<input type="hidden" name="{escape(k)}" value="{escape(params.get(k, ""))}">' for k in ('state', 'redirect_uri'))
    members = ''.join(f'<li><code>{escape(i)}</code> / <code>{escape(r["password"])}</code> — событий: {len(r["events"])}</li>' for i, r in REGISTRY.items())
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ФСП ID · демо-вход</title></head><body>'
            '<main><h1>ФСП ID</h1><p>Имитация входа на локальном стенде. Реальный ФСП ID не используется.</p>'
            + (f'<p role="alert"><strong>{escape(error)}</strong></p>' if error else '') +
            '<form method="post" action="/api/v1/auth/mock-fsp-id/authorize">' + hidden +
            '<p><label>ФСП ID <input name="member_id" maxlength="40" required></label></p>'
            '<p><label>Пароль <input name="password" type="password" maxlength="80" required></label></p>'
            '<p><button type="submit">Войти и разрешить доступ к достижениям</button></p></form>'
            '<p>Демо-участники (ID / пароль):</p><ul>' + members + '</ul></main></body></html>')


def authorize_submit(db, state, member_id, password):
    """Проверяет учётные данные демо-реестра; возвращает одноразовый code или None."""
    flow = _flow(db, state)
    if flow is None or flow.code_hash or not check_password(member_id, password):
        return None
    code = secrets.token_urlsafe(32)
    flow.code_hash, flow.member_id = _sha(code), member_id
    db.commit()
    return code


def exchange(db, code, verifier, state=None):
    """token endpoint: code + PKCE → claims. Код одноразовый."""
    flow = db.scalar(select(FspFlow).where(FspFlow.code_hash == _sha(code)))
    if flow is None or flow.used or now() - _aware(flow.created_at) > FLOW_TTL or (state and flow.state != state):
        return None
    if not hmac.compare_digest(challenge_for(verifier), flow.challenge):
        return None
    flow.used = True
    db.commit()
    return {'sub': flow.member_id, 'user_id': flow.user_id, 'scope': 'openid fsp.achievements'}


def link(db, profile, member_id, unavailable=False):
    """Применяет результат входа к профилю. Возвращает итоговый статус для интерфейса."""
    if unavailable:
        profile.fsp_previous_state, profile.fsp_state = profile.fsp_state, 'unavailable'   # сигнал и история не теряются
        return 'unavailable'
    taken = db.scalar(select(Profile.user_id).where(Profile.fsp_member_id == member_id, Profile.user_id != profile.user_id))
    if taken:
        return 'taken'
    events = events_for(member_id) or []
    try:
        # UNIQUE в БД закрывает гонку после проверки taken; savepoint сохраняет
        # прежнюю связь профиля и оставляет внешнюю транзакцию пригодной для audit.
        with db.begin_nested():
            profile.fsp_previous_state = profile.fsp_state
            profile.fsp_member_id, profile.fsp_evidence = member_id, events
            profile.fsp_signal = signal_for(events)
            profile.fsp_state = 'verified' if events else 'linked-empty'
            db.flush()
    except IntegrityError:
        return 'taken'
    return 'linked' if events else 'empty'


def unlink(profile):
    profile.fsp_previous_state, profile.fsp_state = profile.fsp_state, 'none'
    profile.fsp_member_id, profile.fsp_evidence, profile.fsp_signal = None, [], 0.0
