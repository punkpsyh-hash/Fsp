"""Ограниченный парольный показ синтетического стенда жюри."""
from html import escape
import os
import re

from sqlalchemy import delete, select

from .models import Company, Contact, LoginSession, Mail, Profile, User
from .security import password_hash, password_valid


BLOCKED_PATHS = frozenset({
    '/api/v1/auth/register', '/api/v1/auth/login', '/api/v1/auth/verify',
    '/api/v1/auth/mock-mail', '/api/v1/auth/demo-accounts', '/api/v1/auth/demo-login',
    '/api/v1/candidate/resume-preview',
})

SEED_ACCOUNTS = {
    'demo-candidate-a': ('candidate', 'demo-candidate-a@example.invalid'),
    'demo-candidate-b': ('candidate', 'demo-candidate-b@example.invalid'),
    'demo-candidate-c': ('candidate', 'demo-candidate-c@example.invalid'),
    'demo-candidate-d': ('candidate', 'demo-candidate-d@example.invalid'),
    'demo-candidate-e': ('candidate', 'demo-candidate-e@example.invalid'),
    'demo-employer-x': ('employer', 'demo-employer-x@example.invalid'),
    'demo-employer-y': ('employer', 'demo-employer-y@example.invalid'),
}
INDIVIDUAL_ID = re.compile(r'jury-[0-9a-f]{32}\Z')


def _bounded_integer(name, default, minimum, maximum):
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f'{name} должен быть целым числом') from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f'{name} должен быть от {minimum} до {maximum}')
    return value


def _supported_password_hash(encoded):
    """Проверить формат без подбора или раскрытия пароля."""
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        return (algorithm == 'pbkdf2_sha256' and 600_000 <= int(rounds) <= 2_000_000
                and bool(re.fullmatch(r'[0-9a-f]{32}', salt))
                and bool(re.fullmatch(r'[0-9a-f]{64}', digest)))
    except (AttributeError, TypeError, ValueError):
        return False


def configuration():
    mode = os.environ.get('FSP_JURY_MODE', '0')
    if mode not in {'0', '1'}:
        raise RuntimeError('FSP_JURY_MODE должен быть 0 или 1')
    if mode == '0':
        return None
    individual = os.environ.get('FSP_JURY_INDIVIDUAL_REGISTRATION', '0')
    if individual not in {'0', '1'}:
        raise RuntimeError('FSP_JURY_INDIVIDUAL_REGISTRATION должен быть 0 или 1')
    required = ('FSP_JURY_PASSWORD', 'FSP_JURY_OPERATOR_NAME', 'FSP_JURY_OPERATOR_CONTACT')
    if any(not os.environ.get(key, '').strip() for key in required):
        raise RuntimeError('Для показа жюри нужны пароль и действительные сведения владельца')
    password = os.environ['FSP_JURY_PASSWORD']
    if len(password) < 20 or len(password) > 128 or len(set(password)) < 8:
        raise RuntimeError('Пароль жюри должен содержать от 20 до 128 символов и не менее 8 различных символов')
    if os.environ.get('FSP_JURY_OPERATOR_CONFIRMED') != '1':
        raise RuntimeError('Владелец должен подтвердить действительность сведений оператора')
    if os.environ.get('FSP_JURY_STORAGE_COUNTRY') != 'RU':
        raise RuntimeError('Для этого контура требуется подтверждённое размещение в РФ')
    contact = os.environ['FSP_JURY_OPERATOR_CONTACT'].strip()
    if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', contact) or contact.lower().endswith('.invalid'):
        raise RuntimeError('Нужен действительный email оператора для юридически значимых обращений')
    if os.environ.get('FSP_SMTP_HOST', '').strip() or os.environ.get('FSP_SMTP_ENABLED', '0') != '0':
        raise RuntimeError('В показе жюри внешняя почта отключена')
    if os.environ.get('FSP_COOKIE_SECURE') != '1':
        raise RuntimeError('Парольный показ жюри требует HTTPS и Secure cookie')
    return {
        'password': password,
        'operator_name': os.environ['FSP_JURY_OPERATOR_NAME'].strip(),
        'operator_contact': os.environ['FSP_JURY_OPERATOR_CONTACT'].strip(),
        'individual_registration': individual == '1',
        'max_individual_accounts': _bounded_integer('FSP_JURY_MAX_INDIVIDUAL_ACCOUNTS', 200, 1, 200),
        'registration_rate_limit': _bounded_integer('FSP_JURY_REGISTRATION_RATE_LIMIT', 5, 1, 60),
        'auth_rate_limit': _bounded_integer('FSP_JURY_AUTH_RATE_LIMIT', 10, 1, 60),
    }


def blocked(path):
    path = path.rstrip('/')
    return path in BLOCKED_PATHS or path.startswith((
        '/api/v1/auth/mock-fsp-id/', '/api/v1/candidate/fsp-id/',
    ))


def prepare_accounts(factory, config):
    """Отдельная база: никакой конвертации реальных/произвольных аккаунтов."""
    with factory() as db:
        users = list(db.scalars(select(User)))
        seeded = {user.id: user for user in users if user.demo_seed}
        if set(seeded) != set(SEED_ACCOUNTS) or any(
                (user.role, user.email) != SEED_ACCOUNTS[user.id]
                for user in seeded.values()):
            raise RuntimeError('Жюри требуется отдельная база только с исходными синтетическими аккаунтами')
        individuals = [user for user in users if not user.demo_seed]
        if not config['individual_registration'] and individuals:
            raise RuntimeError('Жюри требуется отдельная база только с исходными синтетическими аккаунтами')
        if len(individuals) > config['max_individual_accounts']:
            raise RuntimeError('Число индивидуальных аккаунтов превышает разрешённый предел')
        if list(db.scalars(select(Mail))):
            raise RuntimeError('В jury-контуре не должно быть записей mock-почты')
        for user in individuals:
            expected_email = user.id + '@example.invalid'
            profile, company, contact = db.get(Profile, user.id), db.get(Company, user.id), db.get(Contact, user.id)
            identity_ok = (INDIVIDUAL_ID.fullmatch(user.id) and user.email == expected_email
                           and user.verified and user.role in {'candidate', 'employer'}
                           and _supported_password_hash(user.password_hash)
                           and 2 <= len(user.label) <= 120)
            role_data_ok = ((user.role == 'candidate' and profile is not None and company is None
                             and contact is not None and contact.value.endswith('@example.invalid'))
                            or (user.role == 'employer' and company is not None and profile is None
                                and contact is None and company.contact.endswith('@example.invalid')))
            if not identity_ok or not role_data_ok:
                raise RuntimeError('Жюри обнаружил некорректный индивидуальный синтетический аккаунт')
        for user in seeded.values():
            if config['individual_registration']:
                # Общие опубликованные данные остаются наполнением стенда, но больше не являются аккаунтами входа.
                user.password_hash = None
                db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            elif not password_valid(config['password'], user.password_hash):
                user.password_hash = password_hash(config['password'])
                # При смене пароля старые сессии не сохраняются.
                db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        db.commit()


def policy_page(kind, config):
    title = 'Политика данных тестового стенда' if kind == 'privacy' else 'Правила подбора и ранжирования'
    owner = '' if config is None else (
        '<p>Владелец и оператор: ' + escape(config['operator_name']) + '. Контакт для вопросов '
        'о данных и работе сервиса: ' + escape(config['operator_contact']) + '.</p>'
    )
    mode = ('<p>Это локальный стенд. Данный текст описывает демонстрацию и не является '
            'политикой неуказанного оператора публичного сервиса.</p>' if config is None else
            '<p>Временный стенд команды «Студия 37» для проверки решения ЛЦТ 2026. '
            'Каждый проверяющий создаёт отдельный синтетический аккаунт: сервер выдаёт '
            'случайный логин в домене example.invalid, настоящая почта и имя не запрашиваются. '
            'Общие seed-аккаунты недоступны для входа. Восстановления пароля по почте нет; '
            'сохраните выданный логин и свой пароль. Стенд принимает не более '
            + str(config['max_individual_accounts']) + ' индивидуальных аккаунтов. Не вводите свои ФИО, '
            'контакты, резюме и сведения других людей.</p>'
            if config['individual_registration'] else
            '<p>Временный стенд команды «Студия 37» для проверки решения ЛЦТ 2026. '
            'Доступ предоставляется проверяющим по паролю. Данные профилей синтетические; '
            'не вводите свои ФИО, контакты, резюме и сведения других людей.</p>')
    if kind == 'privacy':
        body = (
            '<h2>Какие данные обрабатываются</h2><p>Синтетические профили, решения заданий, '
            'предложения и переписка используются для демонстрации и технической проверки. '
            'Работодатель получает контакт синтетического кандидата только после принятия '
            'приглашения или отклика; передачу можно отозвать.</p>'
            '<p>При соединении сервер технически получает сетевой адрес и параметры запроса. '
            'API не ведёт журнал посещений; прокси настроен без access log. Ограничитель '
            'входа хранит хеш адреса в оперативной памяти до перезапуска. Служебные журналы '
            'ошибок могут содержать технические сведения; доступ к ним имеет администратор. '
            'Нельзя обещать отсутствие данных в журналах роутера и провайдера.</p>'
            '<h2>Сессия и хранение</h2><p>Cookie fsp_session необходим для входа, доступен '
            'серверу и закрыт от JavaScript. Срок серверной сессии — 8 часов; выход удаляет '
            'её. Аналитических и рекламных cookies, внешних счётчиков и рассылок нет. '
            'Пароли хранятся как PBKDF2-хеши с отдельной солью. База и резервные копии этого '
            'контура должны оставаться в России.</p>'
            '<p>Показ проводится на время оценки решения. После закрытия администратор '
            'отключает домен и удаляет отдельную демонстрационную базу и её резервные копии '
            'не позднее 30 дней. Служебные журналы ограничены по размеру и удаляются в тот '
            'же срок. Это обязанность администратора, автоматическое удаление не реализовано.</p>'
            '<h2>Получатели и обращения</h2><p>Внешняя почта, иностранный вход и передача '
            'профилей облачной модели отключены. При ручном подключении локальной модели '
            'передаются условия синтетических заданий; решение о публикации принимает автор. '
            'Жюри видит синтетические материалы в пределах кабинета и выданных прав.</p>'
            '<p>Для доступа, исправления, удаления ошибочно введённых сведений, отзыва '
            'согласия и вопросов о работе сервиса обратитесь к указанному оператору. Реальные '
            'данные в демонстрацию не принимаются по назначению; если они введены в свободный '
            'текст вопреки предупреждению, оператор должен обработать обращение и удалить их. '
            'Пароль и отметка согласия на синтетический показ не заменяют основание для '
            'обработки персональных данных или уведомление Роскомнадзора.</p>'
        )
    else:
        body = (
            '<p>Здесь применяются рекомендательные технологии: список кандидатов '
            'упорядочивается по подтверждённым характеристикам и потребности работодателя. '
            'Подбор объясним и не принимает автоматическое решение о найме.</p>'
            '<h2>Источники и входные данные</h2><p>Используются опубликованные синтетические '
            'профили, выбранная специализация и грейд, результат серверного тестирования, '
            'проверенные навыки, демо-достижения ФСП и дата подтверждения. Работодатель '
            'задаёт специализацию, грейд, обязательные и желаемые навыки, формат и бюджет. '
            'Задачи команды добавляют навыки только к желаемым; заявленный стек и практика '
            'работодателя не повышают глобальный грейд.</p>'
            '<h2>Порядок обработки</h2><p>Сначала применяются обязательные фильтры: '
            'публикация профиля, подтверждённые специализация и грейд, необходимые навыки, '
            'формат и зарплатный предел. Оставшиеся профили получают балл: до 45 за тест, '
            'до 35 за совпадение навыков, до 10 за демо-сигнал ФСП и до 10 за актуальность '
            'подтверждения. Компоненты и несовпавшие навыки показываются в выдаче. '
            'При одинаковом балле используется стабильный порядок по идентификатору.</p>'
            '<h2>Ограничения</h2><p>Источники — собственные синтетические данные, локальный '
            'mock ФСП и действия проверяющего; сторонние вакансии не собираются. Контакты '
            'не участвуют в ранжировании. Отсутствие истории ФСП не исключает кандидата. '
            'Независимая калибровка оценки и пилот с реальными кандидатами не проводились. '
            'Нейросеть помогает составлять черновики заданий и рекомендации проверки ответа; '
            'ранжирование выполняется правилами сервера.</p>'
        )
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + title + '</title></head><body><main><h1>' + title + '</h1>'
            + owner + mode + body + '<p>Редакция 11 октября 2026 года.</p>'
            '<p><a href="/legal/privacy">Политика данных</a> · '
            '<a href="/legal/recommendations">Правила подбора</a> · '
            '<a href="/">Вернуться к стенду</a></p></main></body></html>')
