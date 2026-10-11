"""HTTP, HTML/CSS и тестирование: вычисляемые семейства (арифметика, обход структур, правила протокола)."""
import math

from .core import make_brief, multiple, numeric, open_task, pick_distinct, plural, single
from .fam_py import assemble, fence

# ------------------------------------------------------------------ HTTP

METHODS = {  # метод: (безопасный, идемпотентный) по RFC 9110
    'GET': (True, True), 'HEAD': (True, True), 'OPTIONS': (True, True), 'PUT': (False, True),
    'DELETE': (False, True), 'POST': (False, False), 'PATCH': (False, False),
}


def http_methods(rng, grade):
    picks = rng.sample(list(METHODS), rng.randint(4, 5))
    safe = [m for m in picks if METHODS[m][0]]
    idem = [m for m in picks if METHODS[m][1]]
    unsafe_idem = [m for m in picks if METHODS[m][1] and not METHODS[m][0]]
    non_idem = [m for m in picks if not METHODS[m][1]]
    if not safe or not non_idem or not unsafe_idem:
        raise ValueError('вырожденно')
    names = ', '.join(picks)
    data = f'Рассмотрите HTTP-методы: {names}. Опирайтесь на семантику RFC 9110. '
    scenario = f'Нужно проверить знание свойств HTTP-методов {names}.'
    out = {}
    q = 'Какие из перечисленных методов идемпотентны?'
    right = ', '.join(idem)
    alts = [', '.join(safe), ', '.join(non_idem), ', '.join(picks), ', '.join(sorted(set(idem) | set(non_idem[:1]), key=picks.index)),
            ', '.join([m for m in picks if m not in unsafe_idem])]
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Идемпотентные HTTP-методы', data + q, right, wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, 'идемпотентности и безопасности HTTP-методов'))
    ok = [f'{m} безопасен (не должен изменять состояние ресурса)' for m in safe] + [f'{m} идемпотентен, но не безопасен' for m in unsafe_idem]
    bad = [f'{m} безопасен' for m in picks if m not in safe] + [f'{m} идемпотентен' for m in non_idem]
    out['multiple_choice'] = (multiple(rng, 'Свойства HTTP-методов', data + 'Какие утверждения верны? Выберите все верные.',
                                       rng.sample(ok, min(len(ok), rng.randint(2, 3))), rng.sample(bad, min(len(bad), 2)), ['http']),
                              make_brief(rng, 'multiple_choice', scenario, 'идемпотентности и безопасности HTTP-методов'))
    out['numeric'] = (numeric('Число идемпотентных методов', data + 'Сколько из перечисленных методов идемпотентны?', len(idem), 'методов', ['http']),
                      make_brief(rng, 'numeric', scenario, 'идемпотентности и безопасности HTTP-методов'))
    out['open_response'] = (open_task('Безопасность и идемпотентность методов', data + 'Разделите методы на безопасные, идемпотентные и неидемпотентные и объясните различие понятий.',
                                      'методы не разделены либо безопасность и идемпотентность считаются одним понятием',
                                      f'верно названы безопасные методы ({", ".join(safe)}), но нет идемпотентных или объяснения',
                                      f'безопасные: {", ".join(safe)}; идемпотентные: {", ".join(idem)}; неидемпотентные: {", ".join(non_idem)}; безопасный метод не меняет состояние, идемпотентный даёт тот же итог при повторе',
                                      ['http']), make_brief(rng, 'open_response', scenario, 'идемпотентности и безопасности HTTP-методов'))
    return {'spec': rng.choice(['backend', 'qa']), 'skills': ['http'], 'tasks': out}


def http_retry(rng, grade):
    base = rng.choice([1, 2, 3, 5])
    factor = rng.choice([2, 2, 3])
    attempts = rng.randint(4, 6)
    cap = rng.choice([None, base * factor ** 2 + rng.randint(0, 3)]) if grade == 'middle' else None
    delays = []
    for k in range(attempts - 1):
        d = base * factor ** k
        delays.append(min(d, cap) if cap else d)
    total = sum(delays)
    cap_text = f' Задержка не превышает {cap} с.' if cap else ''
    data = (f'Клиент делает до {attempts} попыток запроса. После неудачной попытки с номером k (k = 1, 2, …) он ждёт {base} * {factor}^(k-1) секунд '
            f'перед следующей.{cap_text} Ожидание после последней неудачной попытки не выполняется. ')
    scenario = data.strip()
    topic = 'экспоненциальной задержке повторных HTTP-запросов'
    out = {}
    out['numeric'] = (numeric('Суммарное ожидание при повторах', data + 'Сколько секунд клиент суммарно ждёт, если все попытки закончились неудачей?', total, 'секунд', ['http']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = f'{total} с'
    alts = [f'{sum(delays) + delays[-1]} с', f'{sum(delays[:-1])} с', f'{base * attempts} с', f'{sum(base * factor ** k for k in range(attempts))} с',
            f'{delays[-1]} с', f'{sum(delays) - base} с']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Суммарное ожидание при повторах', data + 'Сколько секунд клиент суммарно ждёт при неудаче всех попыток?', right, wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'число пауз равно {attempts - 1}', f'первая пауза длится {delays[0]} с', f'последняя пауза длится {delays[-1]} с']
    bad = [f'число пауз равно {attempts}', f'первая пауза длится {delays[0] * factor} с', f'последняя пауза длится {delays[-1] * factor} с']
    out['multiple_choice'] = (multiple(rng, 'Паузы между повторами', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['http']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Повторы запросов с задержкой', data + 'Вычислите последовательность пауз и общее ожидание, объясните, зачем добавляют случайный разброс (jitter).',
                                      'паузы не вычислены либо jitter не упомянут',
                                      f'верно вычислены паузы {", ".join(map(str, delays))}, но нет суммы или объяснения jitter',
                                      f'паузы: {", ".join(map(str, delays))} с; сумма {total} с; jitter разводит повторы разных клиентов и снижает синхронные всплески нагрузки на сервер',
                                      ['http']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['http'], 'tasks': out}


def http_pagination(rng, grade):
    total = rng.randint(37, 480)
    size = rng.choice([10, 20, 25, 50])
    page = rng.randint(2, max(2, math.ceil(total / size)))
    pages = math.ceil(total / size)
    offset = (page - 1) * size
    on_page = min(size, max(0, total - offset))
    data = (f'API отдаёт список из {total} записей через параметры page (с 1) и per_page. Размер страницы per_page = {size}. ')
    scenario = data.strip()
    topic = 'расчёте страниц и смещения при пагинации'
    out = {}
    out['numeric'] = (numeric('Число страниц пагинации', data + 'Сколько всего страниц вернёт API при обходе списка до конца?', pages, 'страниц', ['http']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = f'{pages}, на последней странице {total - (pages - 1) * size}'
    alts = [f'{pages - 1}, на последней странице {size}', f'{pages + 1}, на последней странице {total - (pages - 1) * size}',
            f'{total // size}, на последней странице {total % size}', f'{pages}, на последней странице {size}', f'{pages - 1}, на последней странице {total - (pages - 1) * size}']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Страницы и последняя страница', data + 'Сколько страниц и сколько записей на последней странице?', right, wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'для page = {page} смещение (offset) равно {offset}', f'всего страниц {pages}', f'на последней странице {plural(total - (pages - 1) * size, "запись", "записи", "записей")}']
    bad = [f'для page = {page} смещение (offset) равно {page * size}', f'всего страниц {pages + 1}', f'на последней странице {plural(size, "запись", "записи", "записей")}' if total % size else f'всего страниц {pages - 1}']
    out['multiple_choice'] = (multiple(rng, 'Расчёт пагинации', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['http']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Пагинация и смещение', data + f'Рассчитайте число страниц, смещение для page = {page} и число записей на странице {page}; объясните риск пагинации по смещению при вставке записей.',
                                      'расчёты не выполнены либо смещение вычислено от page, а не от page - 1',
                                      f'верно найдено число страниц ({pages}), но нет смещения или анализа риска',
                                      f'страниц {pages}; смещение (page-1)*per_page = {offset}; на странице {page} записей: {on_page}; при вставке записей смещение сдвигает выдачу и вызывает повторы или пропуски, поэтому нужен курсор',
                                      ['http']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['http'], 'tasks': out}


def http_cache(rng, grade):
    max_age = rng.choice([60, 120, 300, 600, 3600])
    age = rng.randint(10, max_age * 2)
    fresh = age < max_age
    remain = max_age - age if fresh else 0
    data = (f'Ответ получен с заголовком Cache-Control: max-age={max_age}. С момента получения прошло {age} с. Валидаторов (ETag) в ответе нет. ')
    scenario = data.strip()
    topic = 'свежести кэшированного HTTP-ответа'
    out = {}
    out['numeric'] = (numeric('Остаток свежести ответа', data + 'Сколько секунд ответ ещё считается свежим? Если ответ устарел, укажите 0.', remain, 'секунд', ['http']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = 'ответ свежий, кэш может отдать его без запроса к серверу' if fresh else 'ответ устарел, кэш должен обратиться к серверу'
    wrongs = ['ответ устарел, кэш должен обратиться к серверу' if fresh else 'ответ свежий, кэш может отдать его без запроса к серверу',
              'ответ нельзя сохранять в кэше вообще', 'ответ свежий, потому что ETag отсутствует']
    out['single_choice'] = (single(rng, 'Свежесть ответа в кэше', data + 'Что должен сделать кэш при новом запросе того же ресурса?', right, wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'max-age задаёт время свежести в секундах', f'возраст ответа {age} с {"меньше" if fresh else "не меньше"} max-age']
    bad = ['max-age задаёт время свежести в миллисекундах', f'возраст ответа {age} с {"не меньше" if fresh else "меньше"} max-age', 'без ETag ответ нельзя сохранить в кэше']
    out['multiple_choice'] = (multiple(rng, 'Cache-Control и свежесть', data + 'Какие утверждения верны? Выберите все верные.', ok, bad[:2], ['http']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Кэширование и повторная проверка', data + 'Определите, свежий ли ответ, и объясните, как ETag и условный запрос If-None-Match позволяют обновить устаревший ответ.',
                                      'свежесть не определена либо ETag описан как обязательный для кэширования',
                                      f'верно определено состояние ответа ({"свежий" if fresh else "устаревший"}), но нет описания условного запроса',
                                      f'ответ {"свежий, остаток " + str(remain) + " с" if fresh else "устарел, так как " + str(age) + " >= " + str(max_age)}; ETag идентифицирует версию, клиент шлёт If-None-Match, сервер отвечает 304 без тела, если версия не изменилась',
                                      ['http']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': rng.choice(['backend', 'frontend']), 'skills': ['http'], 'tasks': out}


def http_idempotency_key(rng, grade):
    n = rng.randint(4, 6)
    keys = ['k1', 'k2', 'k3'][:rng.randint(2, 3)]
    bodies = ['сумма 100', 'сумма 250', 'сумма 40']
    reqs = [(rng.choice(keys), rng.choice(bodies[:2])) for _ in range(n)]
    seen = {}
    created, replays, conflicts = 0, 0, 0
    for key, body in reqs:
        if key not in seen:
            seen[key] = body
            created += 1
        elif seen[key] == body:
            replays += 1
        else:
            conflicts += 1
    if created == n or created == 1 and n < 4:
        raise ValueError('вырожденно')
    rules = ('Сервис создаёт платёж по POST /payments с заголовком Idempotency-Key. Правила: первый запрос с новым ключом создаёт платёж; '
             'повтор с тем же ключом и тем же телом возвращает сохранённый ответ без нового платежа; повтор с тем же ключом, но другим телом, отклоняется как конфликт (409) и платёж не создаётся. ')
    seq = '; '.join(f'{i + 1}) ключ {k}, {b}' for i, (k, b) in enumerate(reqs))
    data = rules + f'Запросы по порядку: {seq}. '
    scenario = data.strip()
    topic = 'идемпотентном создании платежа по ключу идемпотентности'
    out = {}
    out['numeric'] = (numeric('Созданные платежи при повторах', data + 'Сколько платежей будет создано?', created, 'платежей', ['http', 'backend'][:1]),
                      make_brief(rng, 'numeric', scenario, topic))
    right = f'создано {created}, повторов {replays}, конфликтов {conflicts}'
    alts = [f'создано {created + replays}, повторов 0, конфликтов {conflicts}', f'создано {n}, повторов 0, конфликтов 0',
            f'создано {len(keys)}, повторов {replays}, конфликтов {conflicts}', f'создано {created}, повторов {replays + conflicts}, конфликтов 0',
            f'создано {created}, повторов {conflicts}, конфликтов {replays}']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Итог серии запросов с Idempotency-Key', data + 'Каков итог серии: сколько платежей создано, сколько запросов вернули сохранённый ответ и сколько отклонено с 409?', right, wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'создано платежей: {created}', f'отклонено с кодом 409 запросов: {conflicts}', f'запросов, вернувших сохранённый ответ: {replays}']
    bad = [f'создано платежей: {created + 1}', f'отклонено с кодом 409 запросов: {conflicts + 1}', f'запросов, вернувших сохранённый ответ: {replays + 1}']
    out['multiple_choice'] = (multiple(rng, 'Идемпотентность платежа', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['http']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Ключ идемпотентности', data + 'Определите итог серии и объясните, зачем сервис сравнивает тело повторного запроса.',
                                      'итог не определён либо ключ считается способом защиты от подбора',
                                      f'верно найдено число созданных платежей ({created}), но не объяснено сравнение тела',
                                      f'создано {created}, сохранённых ответов {replays}, конфликтов {conflicts}; сравнение тела не даёт повторно использовать ключ для другой операции и выявляет ошибки клиента',
                                      ['http']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['http'], 'tasks': out}


def http_rate_limit(rng, grade):
    limit = rng.choice([5, 10, 20, 60])
    window = rng.choice([10, 30, 60])
    per_window = [rng.randint(limit - 3, limit + 8) for _ in range(rng.randint(3, 4))]
    per_window = [max(1, x) for x in per_window]
    rejected = [max(0, x - limit) for x in per_window]
    data = (f'Сервис разрешает не более {limit} запросов клиента за каждое окно в {window} с; сверх лимита возвращает 429, счётчик в начале нового окна обнуляется. '
            f'Клиент отправил по окнам: {", ".join(map(str, per_window))} запросов. ')
    scenario = data.strip()
    topic = 'ограничении частоты запросов и коде 429'
    out = {}
    out['numeric'] = (numeric('Отклонённые запросы с кодом 429', data + 'Сколько запросов получили ответ 429?', sum(rejected), 'запросов', ['http']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = f'{sum(rejected)} запросов отклонено, {sum(per_window) - sum(rejected)} принято'
    alts = [f'{sum(rejected) + limit} запросов отклонено, {sum(per_window) - sum(rejected) - limit} принято', f'{max(per_window) - limit} запросов отклонено, {sum(per_window) - max(per_window) + limit} принято',
            f'{sum(per_window) - limit} запросов отклонено, {limit} принято', f'{sum(rejected)} запросов отклонено, {sum(per_window)} принято', f'{sum(1 for r in rejected if r)} запросов отклонено, {sum(per_window) - sum(1 for r in rejected if r)} принято']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Лимит запросов и 429', data + 'Сколько запросов отклонено и сколько принято?', right, wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, topic))
    over = [i + 1 for i, r in enumerate(rejected) if r]
    ok = [f'в окне {i} превышен лимит' for i in over[:2]] + [f'всего отклонено {sum(rejected)}']
    under = [i + 1 for i, r in enumerate(rejected) if not r]
    bad = [f'в окне {i} превышен лимит' for i in under[:2]] + [f'всего отклонено {sum(rejected) + 1}']
    if len(ok) < 2 or not bad:
        raise ValueError('вырожденно')
    out['multiple_choice'] = (multiple(rng, 'Окна лимита запросов', data + 'Какие утверждения верны? Выберите все верные.', ok[:3], bad[:2], ['http']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Лимит запросов и поведение клиента', data + 'Посчитайте отклонённые запросы и опишите, как клиент должен реагировать на 429 и заголовок Retry-After.',
                                      'число не посчитано либо 429 трактуется как ошибка сервера',
                                      f'верно посчитано {sum(rejected)} отклонённых, но нет поведения клиента',
                                      f'отклонено {sum(rejected)}: по окнам {", ".join(map(str, rejected))}; клиент должен приостановить повторы на время Retry-After, а не повторять запросы сразу',
                                      ['http']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['http'], 'tasks': out}


STATUS_SCENARIOS = [  # (ситуация, верный код, ошибочные коды, пояснение)
    ('Клиент успешно создал новый ресурс запросом POST, сервер вернул ссылку на него в Location', '201', ['202', '204', '301'], 'ресурс создан'),
    ('Клиент удалил ресурс запросом DELETE, тело ответа не требуется', '204', ['201', '404', '500'], 'успех без тела'),
    ('Запрос без токена авторизации к защищённому методу', '401', ['403', '404', '400'], 'нет учётных данных'),
    ('Пользователь вошёл, но у него нет прав на операцию', '403', ['401', '404', '500'], 'доступ запрещён'),
    ('Ресурс по указанному адресу не существует', '404', ['400', '403', '410'], 'ресурс не найден'),
    ('Тело запроса не является корректным JSON и не разбирается', '400', ['404', '500', '409'], 'некорректный запрос'),
    ('Клиент превысил допустимое число запросов за минуту', '429', ['403', '503', '408'], 'слишком много запросов'),
    ('Сервер принял задачу на длительную обработку и вернёт результат позже', '202', ['200', '201', '204'], 'принято без завершения'),
    ('Ресурс не изменился с момента, указанного в If-None-Match', '304', ['200', '204', '412'], 'не изменён'),
    ('На сервере произошла необработанная внутренняя ошибка', '500', ['400', '502', '503'], 'внутренняя ошибка сервера'),
    ('Запрос создал дубликат уникального значения и конфликтует с текущим состоянием ресурса', '409', ['404', '405', '415'], 'конфликт состояния'),
    ('Ресурс перемещён навсегда на новый адрес, клиент должен использовать новый URL', '301', ['302', '304', '404'], 'постоянное перенаправление'),
]


def http_status_pick(rng, grade):
    picks = rng.sample(STATUS_SCENARIOS, 4)
    first = picks[0]
    scenario = '. '.join(f'{p[0]}' for p in picks[:1]) + '.'
    topic = 'выборе кода состояния HTTP для ситуации'
    out = {}
    wrongs = list(first[2])
    out['single_choice'] = (single(rng, 'Код состояния HTTP', f'{first[0]}. Какой код состояния HTTP подходит для ответа?', first[1], wrongs, ['http']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'{p[1]}: {p[3]}' for p in picks[:3]]
    bad = []
    for i in range(3):
        m = picks[(i + 1) % 3]
        cand = [c for c in picks[i][2] if c != m[1] and c not in {q[1] for q in picks}]
        if cand:
            bad.append(f'{cand[0]}: {m[3]}')
    if len(bad) < 2:
        raise ValueError('мало неверных пар')
    out['multiple_choice'] = (multiple(rng, 'Коды состояния HTTP', 'Какие пары «код: значение» указаны верно? Выберите все верные.',
                                       rng.sample(ok, 2), rng.sample(bad, 2), ['http']),
                              make_brief(rng, 'multiple_choice', 'Нужно проверить знание кодов состояния HTTP.', topic))
    cls = {'2': 'успешные', '3': 'перенаправления', '4': 'ошибки клиента', '5': 'ошибки сервера'}
    codes = [p[1] for p in picks]
    n4 = sum(c[0] == '4' for c in codes)
    out['numeric'] = (numeric('Коды ошибок клиента', f'Даны коды состояния HTTP: {", ".join(codes)}. Сколько из них относятся к классу 4xx (ошибки клиента)?', n4, 'кодов', ['http']),
                      make_brief(rng, 'numeric', f'Даны коды состояния HTTP: {", ".join(codes)}.', 'классах кодов состояния HTTP'))
    listing = '; '.join(f'{p[1]} — {p[3]}' for p in picks)
    out['open_response'] = (open_task('Классы кодов состояния HTTP', f'Даны коды состояния HTTP: {", ".join(codes)}. Отнесите каждый к классу и объясните, чем 401 отличается от 403.',
                                      'классы не названы либо 401 и 403 считаются одним и тем же',
                                      'верно определены классы большинства кодов, но различие 401 и 403 не объяснено',
                                      f'классы: {"; ".join(c + " — " + cls[c[0]] for c in codes)}; 401 означает отсутствие или недействительность учётных данных, 403 — доступ запрещён при известной личности',
                                      ['http']), make_brief(rng, 'open_response', f'Даны коды состояния HTTP: {", ".join(codes)}.', 'классах кодов состояния HTTP'))
    return {'spec': rng.choice(['backend', 'qa']), 'skills': ['http'], 'tasks': out}


# ------------------------------------------------------------------ HTML / CSS

def html_selector_count(rng, grade):
    n = rng.randint(5, 7)
    classes = ['a', 'b']
    items = []
    for i in range(n):
        cls = [c for c in classes if rng.random() < 0.45]
        items.append(cls)
    html = 'ul#menu\n' + '\n'.join(f'  li{"".join("." + x for x in c)}  (пункт {i + 1})' for i, c in enumerate(items))
    sel = rng.choice(['li.a', 'li:not(.a)', 'li.a.b', 'ul > li:nth-child(odd)', 'li:first-child', 'li.a + li', '.b'])
    def match(i, c):
        if sel == 'li.a': return 'a' in c
        if sel == 'li:not(.a)': return 'a' not in c
        if sel == 'li.a.b': return 'a' in c and 'b' in c
        if sel == 'ul > li:nth-child(odd)': return (i + 1) % 2 == 1
        if sel == 'li:first-child': return i == 0
        if sel == 'li.a + li': return i > 0 and 'a' in items[i - 1]
        if sel == '.b': return 'b' in c
    idx = [i + 1 for i, c in enumerate(items) if match(i, c)]
    if not idx or len(idx) == n:
        raise ValueError('вырожденно')
    code = html
    out_text = ', '.join(map(str, idx))
    alts = []
    for _ in range(12):
        sub = sorted(rng.sample(range(1, n + 1), len(idx) if rng.random() < 0.5 else min(n - 1, max(1, len(idx) + rng.choice([-1, 1])))))
        alts.append(', '.join(map(str, sub)))
    truths = [f'селектор {sel} выберет {plural(len(idx), "элемент", "элемента", "элементов")}', f'в выборку попадёт пункт {idx[0]}']
    non = [i for i in range(1, n + 1) if i not in idx]
    falses = [f'селектор {sel} выберет {plural(len(idx) + 1, "элемент", "элемента", "элементов")}', f'в выборку попадёт пункт {non[0]}']
    return assemble(rng, lang='text', code=code, correct_out=out_text, wrong_outs=alts, title='Выбор элементов CSS-селектором',
                    question=f'Номера каких пунктов выберет селектор {sel} (нумерация с 1 по порядку)?', topic='CSS-селекторах и выборе элементов',
                    truths=truths, falses=falses, num_q=f'Сколько элементов выберет селектор {sel}?', num_v=len(idx), num_unit='элементов',
                    open_q=f'Какие пункты выберет селектор {sel} и почему?',
                    zero='пункты не названы либо селектор истолкован неверно',
                    fifty=f'верно названо число элементов ({len(idx)}), но не перечислены пункты или не объяснён селектор',
                    hundred=f'селектор {sel} выбирает пункты {out_text}; объяснено правило селектора по классам, порядку или псевдоклассу',
                    skills=['html'], spec='frontend', scenario_intro='Дано дерево элементов страницы (ul#menu содержит элементы li; точка обозначает класс, #id — идентификатор).',
                    restr='Не меняйте разметку.')


def specificity(sel):
    ids = sel.count('#')
    classes = sel.count('.') + sel.count('[') + sel.count(':hover') + sel.count(':first-child')
    tags = len([t for t in sel.replace('>', ' ').split() if t and t[0].isalpha()])
    return (ids, classes, tags)


def css_specificity(rng, grade):
    pool = ['p', '.note', 'p.note', '#main p', 'div p', '#main .note', 'div > p.note', 'p:first-child', '#main', 'div#main p.note', '.box .note']
    colors = ['red', 'blue', 'green']
    sels = rng.sample(pool, 3)
    spec = [specificity(s) for s in sels]
    order = sorted(range(3), key=lambda i: (spec[i], i))
    win = order[-1]
    if sum(spec[i] == spec[win] for i in range(3)) > 1 and grade == 'junior':
        raise ValueError('равенство')
    css = '\n'.join(f'{s} {{ color: {c}; }}' for s, c in zip(sels, colors))
    html = 'div#main > div.box > p.note  (абзац с текстом)'
    # проверка: все ли селекторы совпадают с элементом
    def applies(sel):
        return sel in {'p', '.note', 'p.note', '#main p', 'div p', '#main .note', 'div > p.note', 'p:first-child', 'div#main p.note', '.box .note'} and sel != '#main' and sel != 'div > p.note' or sel == 'div > p.note'
    # p вложен в .box, который в #main: родитель p — div.box, значит 'div > p.note' совпадает; '#main' сам по себе — div, не p
    matching = [i for i, s in enumerate(sels) if s != '#main']
    if not matching:
        raise ValueError('нет совпадений')
    win = max(matching, key=lambda i: (spec[i], i))
    code = html + '\n\n' + css
    out_text = colors[win]
    wrongs = [c for c in colors if c != out_text] + ['чёрный (цвет по умолчанию)']
    truths = [f'специфичность селектора {sels[win]} равна {spec[win]}' if False else f'победит правило с селектором {sels[win]}',
              f'цвет текста будет {colors[win]}']
    falses = [f'победит правило с селектором {sels[(win + 1) % 3]}' if (win + 1) % 3 in matching and (win + 1) % 3 != win else 'победит правило, которое объявлено первым независимо от специфичности',
              f'цвет текста будет {[c for c in colors if c != colors[win]][0]}']
    return assemble(rng, lang='css', code=code, correct_out=out_text, wrong_outs=wrongs, title='Специфичность CSS-селекторов',
                    question='Какого цвета будет текст абзаца?', topic='специфичности CSS-селекторов',
                    truths=truths, falses=falses, num_q='Сколько идентификаторов (#id) в селекторе победившего правила?', num_v=spec[win][0], num_unit='',
                    open_q='Какого цвета будет текст абзаца и по каким правилам браузер выбирает победителя?',
                    zero='цвет не назван либо победитель выбран только по порядку объявления',
                    fifty=f'верно назван цвет {colors[win]}, но не объяснена специфичность',
                    hundred=f'цвет {colors[win]}; побеждает селектор с большей специфичностью (id, затем классы, затем теги); при равенстве выигрывает более позднее правило',
                    skills=['html'], spec='frontend', scenario_intro='Дано дерево элементов страницы и CSS-правила в порядке объявления.')


def html_form_required(rng, grade):
    fields = [('text', 'name', True), ('email', 'email', True), ('tel', 'phone', False), ('number', 'age', False), ('password', 'pass', True), ('url', 'site', False)]
    chosen = rng.sample(fields, rng.randint(4, 5))
    code = 'form\n' + '\n'.join(f'  input[type={t}][name={n}]{"[required]" if r else ""}' for t, n, r in chosen) + '\n  button[type=submit]'
    req = [n for _, n, r in chosen if r]
    if not req or len(req) == len(chosen):
        raise ValueError('вырожденно')
    out_text = ', '.join(req)
    others = [n for _, n, r in chosen if not r]
    alts = [', '.join(others), ', '.join([n for _, n, _ in chosen]), ', '.join(req[:-1]) or others[0], ', '.join(req + others[:1])]
    truths = [f'пустое поле {req[0]} блокирует отправку формы', f'обязательных полей {len(req)}', f'пустое поле {others[0]} не блокирует отправку (type не делает поле обязательным)']
    falses = [f'пустое поле {others[0]} блокирует отправку формы', f'обязательных полей {len(chosen)}', f'атрибут type="email" делает поле обязательным без required']
    return assemble(rng, lang='text', code=code, correct_out=out_text, wrong_outs=alts, title='Обязательные поля формы',
                    question='Какие поля нужно заполнить, чтобы браузер отправил форму (при пустых остальных)?', topic='атрибуте required и проверке формы HTML',
                    truths=truths, falses=falses, num_q='Сколько полей обязательны для отправки?', num_v=len(req), num_unit='полей',
                    open_q='Какие поля обязательны и как браузерная проверка связана с серверной?',
                    zero='обязательные поля не определены либо проверка браузера принята за достаточную защиту',
                    fifty=f'верно определены обязательные поля ({out_text}), но не объяснена серверная проверка',
                    hundred=f'обязательны: {out_text}; атрибут required проверяется браузером; клиентская проверка обходится, поэтому сервер обязан валидировать данные повторно',
                    skills=['html'], spec='frontend', scenario_intro='Дана форма на странице: перечислены её поля (атрибуты в квадратных скобках).')


# ------------------------------------------------------------------ Тестирование

def qa_boundary(rng, grade):
    lo = rng.randint(1, 30)
    hi = lo + rng.randint(5, 80)
    field = rng.choice(['возраст участника', 'количество товаров', 'длина пароля', 'размер файла в МБ', 'число попыток'])
    two = [lo - 1, lo, hi, hi + 1]
    three = sorted({lo - 1, lo, lo + 1, hi - 1, hi, hi + 1})
    data = f'Поле «{field}» принимает целые значения от {lo} до {hi} включительно. '
    scenario = data.strip()
    topic = 'анализе граничных значений'
    out = {}
    out['numeric'] = (numeric('Граничные значения диапазона', data + 'Сколько тестовых значений даёт двухточечный анализ граничных значений (две пары: ближайшие значения у каждой границы — внутри и снаружи)?', 4, 'значения', ['testing']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = ', '.join(map(str, two))
    alts = [f'{lo}, {hi}', f'{lo - 1}, {hi + 1}', f'{lo}, {lo + 1}, {hi - 1}, {hi}', f'{lo - 1}, {lo}, {hi - 1}, {hi}', f'{lo + 1}, {hi - 1}', f'{lo}, {(lo + hi) // 2}, {hi}']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Граничные значения', data + 'Какой набор значений является двухточечным анализом граничных значений (по два значения у каждой границы: на границе и сразу за ней)?', right, wrongs, ['testing']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'значение {lo} допустимо', f'значение {hi} допустимо', f'значение {lo - 1} недопустимо', f'значение {hi + 1} недопустимо']
    bad = [f'значение {lo - 1} допустимо', f'значение {hi + 1} допустимо', f'значение {hi} недопустимо', f'значение {lo} недопустимо']
    out['multiple_choice'] = (multiple(rng, 'Допустимые и недопустимые значения', data + 'Какие утверждения верны? Выберите все верные.', rng.sample(ok, rng.randint(2, 3)), rng.sample(bad, 2), ['testing']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Тесты граничных значений', data + 'Перечислите значения для проверки границ и ожидаемые результаты, объясните выбор.',
                                      'граничные значения не названы либо проверена только середина диапазона',
                                      f'названы значения у одной границы либо без ожидаемых результатов',
                                      f'{lo - 1} отклоняется, {lo} принимается, {hi} принимается, {hi + 1} отклоняется; ошибки чаще возникают на границах и при неверных сравнениях < и <=',
                                      ['testing']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


def qa_states(rng, grade):
    names = rng.choice([['new', 'queued', 'done', 'failed'], ['draft', 'review', 'published', 'rejected'], ['open', 'paid', 'shipped', 'closed']])
    a, b, c, d = names
    edges = {a: [b], b: [c, d], c: [], d: [b]}
    if rng.random() < 0.4:
        edges[d] = [b, a]
    trans = [f'{s}→{t}' for s in names for t in edges[s]]
    data = (f'Заданы состояния {", ".join(names)}. Допустимые переходы: {", ".join(trans)}. Состояние {c} терминальное. ')
    scenario = data.strip()
    topic = 'проверке допустимых переходов конечного автомата'
    path = [a]
    steps = rng.randint(3, 5)
    for _ in range(steps):
        nxt = edges[path[-1]]
        if not nxt:
            break
        path.append(rng.choice(nxt))
    final = path[-1]
    seq_text = ' → '.join(path)
    out = {}
    out['single_choice'] = (single(rng, 'Состояние после переходов', data + f'Объект начинает в состоянии {a} и проходит допустимые переходы: {seq_text}. В каком состоянии он окажется?',
                                   final, [n for n in names if n != final], ['testing']),
                            make_brief(rng, 'single_choice', scenario, topic))
    all_pairs = [(s, t) for s in names for t in names if s != t]
    valid = [p for p in all_pairs if p[1] in edges[p[0]]]
    invalid = [p for p in all_pairs if p not in valid]
    out['multiple_choice'] = (multiple(rng, 'Допустимые переходы', data + 'Какие из переходов допустимы? Выберите все допустимые.',
                                       [f'{s}→{t}' for s, t in rng.sample(valid, 2)], [f'{s}→{t}' for s, t in rng.sample(invalid, 2)], ['testing']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    state = rng.choice([s for s in names])
    out['numeric'] = (numeric('Исходящие переходы состояния', data + f'Сколько допустимых переходов выходит из состояния {state}?', len(edges[state]), 'переходов', ['testing']),
                      make_brief(rng, 'numeric', scenario, topic))
    reach = {a}
    stack = [a]
    while stack:
        cur = stack.pop()
        for nx in edges[cur]:
            if nx not in reach:
                reach.add(nx); stack.append(nx)
    out['open_response'] = (open_task('Тесты переходов автомата', data + 'Предложите набор тестов: допустимые переходы, недопустимые переходы и терминальное состояние.',
                                      'тесты не предложены либо проверены только допустимые переходы',
                                      'предложены допустимые переходы, но нет проверки запрещённых',
                                      f'допустимые переходы: {", ".join(trans)}; недопустимые, например {invalid[0][0]}→{invalid[0][1]}, должны отклоняться; из терминального {c} переходов нет',
                                      ['testing']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


def qa_combinations(rng, grade):
    params = rng.sample([('браузер', rng.randint(2, 4)), ('ОС', rng.randint(2, 3)), ('язык интерфейса', rng.randint(2, 3)), ('тариф', rng.randint(2, 4)), ('способ оплаты', rng.randint(2, 4))], rng.randint(3, 4))
    sizes = [s for _, s in params]
    total = math.prod(sizes)
    top2 = sorted(sizes)[-2:]
    pairwise_min = top2[0] * top2[1]
    desc = ', '.join(f'{n}: {s}' for n, s in params)
    data = f'Тестируется форма с параметрами и числом значений: {desc}. '
    scenario = data.strip()
    topic = 'числе комбинаций тестовых конфигураций'
    out = {}
    out['numeric'] = (numeric('Полный перебор конфигураций', data + 'Сколько конфигураций даёт полный перебор всех сочетаний?', total, 'конфигураций', ['testing']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = str(total)
    alts = [str(sum(sizes)), str(total + sizes[0]), str(total * 2), str(math.prod(sizes[:-1])), str(sum(sizes) * len(sizes))]
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Сочетания параметров', data + 'Сколько тестов нужно для полного перебора всех сочетаний значений?', right, wrongs, ['testing']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'полный перебор требует {total} конфигураций', f'попарное тестирование покрывает все пары значений меньшим числом тестов, чем полный перебор', f'нижняя оценка числа тестов для всех пар равна {pairwise_min}']
    bad = [f'полный перебор требует {sum(sizes)} конфигураций', 'попарное тестирование всегда требует столько же тестов, сколько полный перебор', f'нижняя оценка числа тестов для всех пар равна {pairwise_min + 1}']
    out['multiple_choice'] = (multiple(rng, 'Полный перебор и попарное тестирование', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['testing']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Сокращение числа тестов', data + 'Вычислите число конфигураций полного перебора и предложите способ сократить набор, сохранив покрытие.',
                                      'число не вычислено либо предложено случайно выбрать тесты',
                                      f'верно вычислено {total}, но способ сокращения не назван',
                                      f'полный перебор — {total} конфигураций; сокращение — попарное тестирование (pairwise) или классы эквивалентности; для всех пар нужно не меньше {pairwise_min} тестов',
                                      ['testing']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


def qa_coverage(rng, grade):
    stmts = rng.randint(20, 80)
    covered = rng.randint(stmts // 3, stmts - 3)
    branches = rng.randint(8, 30)
    bcov = rng.randint(2, branches - 1)
    pct = round(covered / stmts * 100, 1)
    bpct = round(bcov / branches * 100, 1)
    data = f'Отчёт покрытия: из {stmts} исполняемых строк тестами выполнено {covered}; из {branches} ветвлений обойдено обе стороны у {bcov}. '
    scenario = data.strip()
    topic = 'метриках покрытия кода тестами'
    out = {}
    out['numeric'] = (numeric('Покрытие строк', data + 'Чему равно покрытие строк в процентах? Округлите до десятых.', pct, '%', ['testing']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = f'строк {pct}%, ветвлений {bpct}%'
    alts = [f'строк {bpct}%, ветвлений {pct}%', f'строк {round(100 - pct, 1)}%, ветвлений {bpct}%', f'строк {pct}%, ветвлений {round(100 - bpct, 1)}%', f'строк {round(covered / branches * 100, 1)}%, ветвлений {bpct}%']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Покрытие строк и ветвлений', data + 'Каковы покрытие строк и покрытие ветвлений?', right, wrongs, ['testing']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'не покрыто {stmts - covered} строк', f'покрытие ветвлений равно {bpct}%', 'высокое покрытие не гарантирует отсутствие дефектов']
    bad = [f'не покрыто {covered + 1} строк', f'покрытие ветвлений равно {pct}%' if pct != bpct else 'покрытие ветвлений равно 100%', 'покрытие 100% гарантирует отсутствие дефектов']
    out['multiple_choice'] = (multiple(rng, 'Метрики покрытия', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['testing']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Покрытие и качество тестов', data + 'Вычислите оба покрытия и объясните, почему высокое покрытие не доказывает качество тестов.',
                                      'покрытия не вычислены либо покрытие приравнено к отсутствию дефектов',
                                      f'вычислены покрытия ({pct}% и {bpct}%), но нет объяснения ограничений',
                                      f'строки {pct}%, ветвления {bpct}%; покрытие показывает выполненный код, а не наличие проверок результата; тесты без утверждений могут покрывать код и пропускать дефекты',
                                      ['testing']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


def qa_defects(rng, grade):
    before = rng.randint(20, 90)
    after = rng.randint(2, 15)
    kloc = rng.choice([5, 8, 10, 20, 25])
    total = before + after
    dre = round(before / total * 100, 1)
    density = round(total / kloc, 2)
    data = f'В релизе {kloc} тысяч строк кода. Тестирование до выпуска нашло {before} дефектов, после выпуска пользователи сообщили ещё {after}. '
    scenario = data.strip()
    topic = 'метриках дефектов: плотность и эффективность устранения'
    out = {}
    out['numeric'] = (numeric('Эффективность поиска дефектов', data + 'Чему равна эффективность устранения дефектов DRE = найдено до выпуска / всего найдено, в процентах? Округлите до десятых.', dre, '%', ['testing']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = f'плотность {fmt(density)} дефекта на тысячу строк, DRE {dre}%'
    alts = [f'плотность {fmt(round(before / kloc, 2))} дефекта на тысячу строк, DRE {dre}%', f'плотность {fmt(density)} дефекта на тысячу строк, DRE {round(after / total * 100, 1)}%',
            f'плотность {fmt(round(total * kloc, 2))} дефекта на тысячу строк, DRE {dre}%', f'плотность {fmt(round(after / kloc, 2))} дефекта на тысячу строк, DRE {round(after / total * 100, 1)}%']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Плотность дефектов и DRE', data + 'Чему равны плотность дефектов (всего найденных на тысячу строк) и DRE?', right, wrongs, ['testing']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'всего найдено {total} дефектов', f'DRE равна {dre}%', 'дефекты, найденные после выпуска, снижают DRE']
    bad = [f'всего найдено {before} дефектов', f'DRE равна {round(after / total * 100, 1)}%', 'дефекты после выпуска не влияют на DRE']
    out['multiple_choice'] = (multiple(rng, 'Метрики дефектов', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['testing']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Метрики качества релиза', data + 'Вычислите плотность дефектов и DRE и объясните, как их использовать при решении о выпуске.',
                                      'метрики не вычислены либо DRE путается с долей пропущенных дефектов',
                                      f'вычислена одна метрика ({dre}% DRE), но нет второй или применения',
                                      f'всего {total} дефектов, плотность {fmt(density)} на тысячу строк, DRE {dre}%; метрики сравнивают с прошлыми релизами и тяжестью дефектов, одна цифра не решает вопрос о выпуске',
                                      ['testing']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


def fmt(x):
    return ('%g' % x).replace('.', ',')


def qa_equivalence(rng, grade):
    a, b = sorted(rng.sample(range(5, 60), 2))
    c = b + rng.randint(5, 30)
    prices = rng.sample([0, 10, 20, 30, 50], 3)
    classes = [(0, a - 1, prices[0]), (a, b - 1, prices[1]), (b, c, prices[2])]
    data = (f'Скидка зависит от числа товаров в заказе n (целое от 0 до {c}): при n от 0 до {a - 1} скидка {prices[0]}%, от {a} до {b - 1} — {prices[1]}%, от {b} до {c} — {prices[2]}%. '
            f'Значения вне диапазона недопустимы. ')
    scenario = data.strip()
    topic = 'классах эквивалентности и выборе тестовых значений'
    out = {}
    n_valid = len(classes)
    out['numeric'] = (numeric('Классы эквивалентности скидки', data + 'Сколько допустимых классов эквивалентности нужно покрыть тестами (по одному значению из каждого)?', n_valid, 'класса', ['testing']),
                      make_brief(rng, 'numeric', scenario, topic))
    probe = rng.randint(a, b - 1)
    out['single_choice'] = (single(rng, 'Скидка для значения', data + f'Какая скидка применяется при n = {probe}?', f'{prices[1]}%', [f'{p}%' for p in dict.fromkeys(prices + [prices[1] + 5]) if p != prices[1]][:3], ['testing']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'значения {a} и {a - 1} относятся к разным классам', f'значения {b} и {c} относятся к одному классу', f'значение {c + 1} недопустимо']
    bad = [f'значения {a} и {a - 1} относятся к одному классу', f'значения {b - 1} и {b} относятся к одному классу', f'значение {c} недопустимо']
    out['multiple_choice'] = (multiple(rng, 'Классы эквивалентности', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['testing']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Разбиение на классы и границы', data + 'Выделите классы эквивалентности и предложите значения для проверки, включая границы между классами.',
                                      'классы не выделены либо проверяется одно значение',
                                      f'выделены допустимые классы, но нет границ или недопустимых значений',
                                      f'допустимые классы: 0–{a - 1}, {a}–{b - 1}, {b}–{c}; недопустимые: меньше 0 и больше {c}; границы: {a - 1}, {a}, {b - 1}, {b}, {c}, {c + 1}',
                                      ['testing']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


FAMILIES = [http_methods, http_retry, http_pagination, http_cache, http_idempotency_key, http_rate_limit, http_status_pick,
            html_selector_count, css_specificity, html_form_required,
            qa_boundary, qa_states, qa_combinations, qa_coverage, qa_defects, qa_equivalence]
