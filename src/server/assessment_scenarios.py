"""Авторские сценарии v5: чтение фиксированного кода и разбор данных.

Генератор не исполняет код кандидата (и не принимает его). Диапазоны и матрица
фиксированы; сопоставимость профессиональной сложности ещё не калибрована.
parameters — только данные условия. answer/explanation/explanation_answer/topic
— private snapshot; explanation_answer связывает разбор с сохранённым ключом.
"""
from contextvars import ContextVar
from difflib import SequenceMatcher
import itertools
import json
import random

# scenarios-v6: выбор неверных вариантов без подсказок формой (длина, сходство,
# совпадение чисел с условием). Валидация v5 показала, что «самый короткий вариант»
# давал 29–38% верных при случайных 25%. v5 остаётся прежним побайтно.
_DEBIAS = ContextVar('scenario_debias', default=False)
_SAMPLE_TRIPLES = 150


def render(value):
    return json.dumps(value, ensure_ascii=False, separators=(', ', ': '))


def _question(family, skill, title, params, answer, distractors, topic, reason, rng):
    if _DEBIAS.get():
        distractors = _augment(answer, distractors)
    options = list(dict.fromkeys([render(answer)] + [render(v) for v in distractors]))
    if len(options) < 4:
        raise ValueError('Недостаточно различных вариантов сценария: ' + family)
    if _DEBIAS.get():
        options = [options[0]] + _balanced_distractors(options[0], options[1:], title, rng)
    else:
        options = [options[0]] + rng.sample(options[1:], 3)
    rng.shuffle(options)
    return {'id': family, 'family': family, 'skill': skill, 'title': title,
            'parameters': params, 'options': options, 'answer': render(answer),
            'topic': topic, 'explanation': reason, 'explanation_answer': render(answer)}


def _augment(answer, distractors):
    """v6: пополняет пул правдоподобных неверных вариантов мутациями верного ответа.

    Мутации сохраняют структуру и состав элементов условия (длина, запись и числа похожи на верный
    ответ), поэтому форма не выдаёт верный вариант длиной, составом или тем, что его числа есть в условии.
    """
    extra = []
    if isinstance(answer, bool):
        return list(distractors)
    if isinstance(answer, int):
        return list(distractors)   # скаляры: числа вне условия выдавали бы ответ, оставляем авторские варианты
    elif isinstance(answer, list) and answer and all(isinstance(x, (int, str)) and not isinstance(x, bool) for x in answer):
        universe = list(dict.fromkeys(
            [x for v in [answer] + [d for d in distractors if isinstance(d, list)]
             for x in v if isinstance(x, (int, str)) and not isinstance(x, bool)]))
        reference = max([d for d in distractors if isinstance(d, list) and set(universe) <= set(d)] or [universe],
                        key=len)
        order = {x: i for i, x in enumerate(reference)}
        keep_order = answer == sorted(answer, key=lambda x: order.get(x, 0)) or answer == sorted(answer)

        def normal(v):
            return sorted(v, key=lambda x: order.get(x, 0)) if keep_order and all(x in order for x in v) else v

        base = list(answer)
        outside = [x for x in universe if x not in base]
        extra += [normal(base + [x]) for x in outside]
        extra += [base[:i] + base[i + 1:] for i in range(len(base))]
        extra += [normal(base[:i] + [x] + base[i + 1:]) for i in range(len(base)) for x in outside]
        extra += [base[:i] + [base[i + 1], base[i]] + base[i + 2:] for i in range(len(base) - 1)]
    elif isinstance(answer, list) and answer and all(isinstance(r, list) and len(r) == 2 for r in answer):
        for i, (key, value) in enumerate(answer):
            for delta in (-1, 1, 2):
                if isinstance(value, int) and value + delta >= 0:
                    extra.append(answer[:i] + [[key, value + delta]] + answer[i + 1:])
            extra.append(answer[:i] + answer[i + 1:])
        for i in range(len(answer)):
            for j in range(i + 1, len(answer)):
                if answer[i][1] != answer[j][1]:       # обмен значениями сохраняет состав чисел в ответе
                    swapped = [list(r) for r in answer]
                    swapped[i][1], swapped[j][1] = answer[j][1], answer[i][1]
                    extra.append(swapped)
    return list(distractors) + [e for e in extra if e != answer and e != []]


def _tokens(text):
    return set(''.join(c if c.isalnum() else ' ' for c in text).split())


def _rank(value, others):
    """Место значения среди четырёх (0..3); равные делят место пополам."""
    return sum(value > o for o in others) + 0.5 * sum(value == o for o in others)


def _balanced_distractors(answer, pool, title, rng):
    """Три неверных варианта, при которых верный не выделяется признаком.

    Целевое место верного ответа по длине, «похожести на остальные» и
    совпадению чисел с условием выбирается равновероятно; подбирается тройка,
    ближе всего к цели. При пуле из трёх вариантов выбора нет.
    """
    if len(pool) <= 3:
        return list(pool)
    target = [rng.choice((0, 1, 2, 3)) for _ in range(3)]
    shown = _tokens(title)
    ratios = {}

    def ratio(a, b):
        key = (a, b) if a <= b else (b, a)
        if key not in ratios:
            ratios[key] = SequenceMatcher(None, a, b).ratio()
        return ratios[key]

    def similarity(option, others):
        return sum(ratio(option, o) for o in others if o != option)

    triples = [tuple(rng.sample(pool, 3)) for _ in range(_SAMPLE_TRIPLES)]
    best, best_cost = None, None
    for triple in triples:
        four = (answer,) + triple
        sims = [similarity(o, four) for o in four]
        overlaps = [len(_tokens(o) & shown) for o in four]
        ranks = (_rank(len(answer), [len(o) for o in triple]),
                 _rank(sims[0], sims[1:]),
                 _rank(overlaps[0], overlaps[1:]))
        cost = sum(abs(r - t) for r, t in zip(ranks, target))
        if best_cost is None or cost < best_cost:
            best, best_cost = triple, cost
    return list(best)


def _lists(domain, answer):
    # Содержательные альтернативные выборки/порядки из того же условия.
    candidates = [[], domain, list(reversed(domain)), list(reversed(answer))]
    candidates += [list(v) for n in range(1, min(3, len(domain)) + 1)
                   for v in itertools.combinations(domain, n)]
    return candidates


def _records(rng, middle):
    ids = rng.sample(range(10, 99), 6 if middle else 4)
    records = [{'id': i, 'active': bool(rng.randrange(2)), 'value': rng.randint(1, 9)} for i in ids]
    records[0]['active'], records[1]['active'] = True, False
    return records


def _python(rng, middle):
    rows = []
    records, minimum = _records(rng, middle), rng.randint(2, 6)
    p = {'records': records, 'minimum': minimum, 'middle': middle}
    predicate = f"r['active'] and r['value'] >= {minimum}" if middle else "r['active']"
    answer = [r['id'] for r in records if r['active'] and (not middle or r['value'] >= minimum)]
    rows.append(_question('py-selection', 'python',
        f"records = {records!r}\nresult = [r['id'] for r in records if {predicate}]\nКакой result вернётся (порядок исходный)?",
        p, answer, _lists([r['id'] for r in records], answer), 'Предикаты и выбор данных в обработчике',
        'Проходите записи в исходном порядке: отбрасывайте inactive' +
        (f' и записи с value меньше {minimum}' if middle else '') + f'. Идентификаторы оставшихся: {render(answer)}.', rng))

    values = rng.sample(range(10, 99), 3)
    p = {'values': values, 'fresh_second': bool(rng.randrange(2)) if middle else False}
    second_arg = ', []' if p['fresh_second'] else ''
    answer = [values[1]] if p['fresh_second'] else values[:2]
    title = ("def remember(value, bucket=[]):\n    bucket.append(value)\n    return bucket.copy()\n"
             f"first = remember({values[0]})\nsecond = remember({values[1]}{second_arg})\n")
    if middle:
        title += f'third = remember({values[2]})\n'
    title += 'Каков сохранённый second после всех вызовов?'
    rows.append(_question('py-default', 'python', title, p, answer,
        _lists(values, answer), 'Изменяемый default и копирование результата',
        'Default bucket создаётся один раз. Явный [] создаёт отдельный bucket; copy() фиксирует результат вызова. '
        f'second содержит {render(answer)} и последующий вызов его не меняет.', rng))

    original, appended = rng.randint(10, 39), rng.randint(50, 79)
    deep = bool(rng.randrange(2)) if middle else False
    p = {'original': original, 'appended': appended, 'deep': deep}
    answer = [original] if deep else [original, appended]
    copy_code = 'copy.deepcopy(state)' if deep else 'state.copy()'
    rows.append(_question('py-copy', 'python',
        f"import copy\nstate = {{'queue': [{original}]}}\nbackup = {copy_code}\nstate['queue'].append({appended})\nКаков backup['queue']?",
        p, answer, [[], [appended], [original], [original, appended], [appended, original]] +
        ([[original, appended, appended], [original, original], [appended, appended]] if _DEBIAS.get() else []),
        'Поверхностная и глубокая копия вложенного состояния',
        ('deepcopy копирует вложенный список.' if deep else 'dict.copy копирует словарь, но queue остаётся общим списком.') +
        f' Поэтому backup.queue: {render(answer)}.', rng))

    records = _records(rng, middle)
    for index, record in enumerate(records):
        record['value'] = 0 if index == 1 else rng.randint(1, 8)
    limit = rng.randint(3, 7)
    p = {'records': records, 'limit': limit, 'middle': middle}
    answer = [r['id'] for r in records if r['value'] == 0 or (middle and r['value'] > limit)]
    extra = f"\n        if row['value'] > {limit}:\n            raise ValueError('limit')" if middle else ''
    rows.append(_question('py-errors', 'python',
        f"rows = {records!r}\nfailed = []\nfor row in rows:\n    try:{extra}\n        result = 100 // row['value']\n    except (ZeroDivisionError, ValueError):\n        failed.append(row['id'])\nКакие id попадут в failed?",
        p, answer, _lists([r['id'] for r in records], answer), 'Диагностика ошибок и граница try/except',
        'В failed попадают только строки, где деление на ноль' +
        (f' либо явная проверка value > {limit} вызывает исключение' if middle else ' вызывает исключение') +
        f': {render(answer)}. Исключение одной строки не прерывает цикл.', rng))
    return rows


def _javascript(rng, middle):
    rows = []
    records, minimum = _records(rng, middle), rng.randint(2, 6)
    p = {'records': records, 'minimum': minimum, 'middle': middle}
    predicate = f'r.active && r.value >= {minimum}' if middle else 'r.active'
    answer = [r['id'] for r in records if r['active'] and (not middle or r['value'] >= minimum)]
    rows.append(_question('js-selection', 'javascript',
        f'const records = {render(records)};\nconst result = records.filter(r => {predicate}).map(r => r.id);\nКаков result?',
        p, answer, _lists([r['id'] for r in records], answer), 'filter/map в обработчике списка',
        f'filter проверяет каждую запись и сохраняет порядок; map берёт только id. Результат: {render(answer)}.', rng))

    first, second = rng.randint(10, 39), rng.randint(50, 79)
    clone = bool(rng.randrange(2)) if middle else False
    p = {'first': first, 'second': second, 'clone': clone}
    copy_code = '{...state, items: [...state.items]}' if clone else '{...state}'
    answer = [first] if clone else [first, second]
    rows.append(_question('js-state', 'javascript',
        f'const state = {{items: [{first}]}};\nconst next = {copy_code};\nnext.items.push({second});\nКаков state.items?',
        p, answer, [[], [first], [second], [first, second], [second, first]] +
        ([[first, second, second], [first, first], [second, second]] if _DEBIAS.get() else []),
        'Копирование состояния и вложенные ссылки',
        ('Копия items имеет отдельный массив.' if clone else 'Spread копирует объект, но ссылка items остаётся общей.') +
        f' state.items: {render(answer)}.', rng))

    ids = rng.sample(range(10, 99), 3 if middle else 2)
    completion = rng.sample(ids, len(ids))
    guarded = bool(rng.randrange(2))
    p = {'started': ids, 'completed': completion, 'guarded': guarded}
    answer = ids[-1] if guarded else completion[-1]
    code = 'if (requestId === latestRequestId) setResult(requestId);' if guarded else 'setResult(requestId);'
    rows.append(_question('js-race', 'javascript',
        f'Поиск запускает запросы с requestId {render(ids)} в этом порядке. latestRequestId обновляется при запуске. '
        f'Все успешные ответы приходят в порядке {render(completion)}. Обработчик ответа: {code}\n'
        'Какой requestId будет в result после всех ответов?', p, answer,
        ids + [0, -1], 'Порядок асинхронных ответов и устаревший результат',
        ('Guard позволяет записать только последний запущенный запрос.' if guarded else
         'Без guard каждый ответ перезаписывает result, включая устаревший.') + f' Итоговый requestId: {answer}.', rng))

    labels = rng.sample(['Гость', 'Кандидат', 'Компания', 'Участник', 'Без имени'], 2)
    value = rng.choice([None, '', 0, 'Автор'])
    nullish = bool(rng.randrange(2)) if middle else True
    p = {'value': value, 'fallback': labels[0], 'nullish': nullish}
    answer = labels[0] if value is None or (not nullish and value in ['', 0]) else value
    known = ['Гость', 'Кандидат', 'Компания', 'Участник', 'Без имени', 'Автор']
    comment = ('// Подписи интерфейса: ' + ', '.join(known) + '\n') if _DEBIAS.get() else ''
    rows.append(_question('js-fallback', 'javascript',
        comment + f'const value = {render(value)};\nconst label = value '+('??' if nullish else '||')+
        f' {render(labels[0])};\nКаково значение label? (JSON-запись)', p, answer,
        ([None, '', 0] + known) if _DEBIAS.get() else [None, '', 0, 'Автор'] + labels, 'nullish coalescing и ложные значения',
        ('?? заменяет только null/undefined.' if nullish else '|| заменяет также пустую строку и 0.') +
        f' Здесь label = {render(answer)}.', rng))
    return rows


def _aggregate_decoys(orders, users, minimum, middle, answer, all_sums):
    """Типичные ошибки на тех же данных: без WHERE, без HAVING, > вместо >=, COUNT вместо SUM, не те статусы."""
    def totals(rows, use=lambda o: True, count=False):
        result = {}
        for o in rows:
            if use(o):
                result[o['user_id']] = result.get(o['user_id'], 0) + (1 if count else o['amount'])
        return result

    def pairs(sums, test=lambda v: True):
        return [[k, v] for k, v in sorted(sums.items()) if test(v)]

    decoys = [
        pairs(totals(orders), lambda v: v >= minimum),                       # игнорирован WHERE
        pairs(totals(orders, lambda o: not middle or o['status'] == 'paid'), lambda v: v > minimum),
        pairs(totals(orders, lambda o: not middle or o['status'] == 'paid', True), lambda v: v >= minimum),
        pairs(totals(orders, lambda o: o['status'] != 'paid' if middle else True), lambda v: v >= minimum),
        all_sums,                                                             # без HAVING
        sorted(answer, key=lambda r: -r[1]),                                  # другой порядок
    ]
    return [d for d in decoys if d != answer and d]


def _sql(rng, middle):
    users = [{'id': i, 'email': None if index % 3 == 1 else ('' if index % 3 == 2 else f'u{i}@example.invalid')}
             for index, i in enumerate(rng.sample(range(10, 99), 4))]
    orders = [{'id': i, 'user_id': rng.choice(users)['id'], 'amount': rng.randint(1, 12),
               'status': rng.choice(['paid', 'new'])} for i in rng.sample(range(100, 999), 6 if middle else 4)]
    orders[0]['status'] = 'paid'
    rows = []
    empty = bool(rng.randrange(2)) if middle else False
    query = "SELECT id FROM users WHERE email IS NULL" + (" OR email = ''" if empty else '') + ' ORDER BY id'
    answer = sorted(u['id'] for u in users if u['email'] is None or (empty and u['email'] == ''))
    rows.append(_question('sql-null-data', 'sql',
        f'SQLite. users(id INTEGER, email TEXT) = {render(users)}.\n{query};\nКаков список id результата?',
        {'users': users, 'include_empty': empty, 'query': query}, answer, _lists(sorted(u['id'] for u in users), answer),
        'NULL отдельно от пустой строки', f'IS NULL выбирает NULL; пустая строка требует отдельного условия. '
        f'ORDER BY id задаёт результат: {render(answer)}.', rng))

    minimum = rng.randint(2, 5)
    p = {'users': users, 'orders': orders, 'minimum': minimum, 'middle': middle}
    where = " WHERE status = 'paid'" if middle else ''
    query = ('SELECT user_id, SUM(amount) FROM orders' + where +
             f' GROUP BY user_id HAVING SUM(amount) >= {minimum} ORDER BY user_id')
    sums = {}
    for o in orders:
        if not middle or o['status'] == 'paid':
            sums[o['user_id']] = sums.get(o['user_id'], 0) + o['amount']
    answer = [[key, value] for key, value in sorted(sums.items()) if value >= minimum]
    p['query'] = query
    all_sums = [[key, value] for key, value in sorted(sums.items())]
    rows.append(_question('sql-aggregate-data', 'sql',
        f'SQLite. orders(id, user_id, amount, status) = {render(orders)}.\n{query};\nКаковы строки [user_id, сумма]?',
        p, answer, (_aggregate_decoys(orders, users, minimum, middle, answer, all_sums) + [[], [[u['id'], 0] for u in users]] + [[[key, value]] for key, value in sorted(sums.items())] if _DEBIAS.get() else
        [[], all_sums, [[u['id'], 0] for u in users]] +
        [[[key, value]] for key, value in sorted(sums.items())] + [[[0, sum(o['amount'] for o in orders)]]]),
        'WHERE, GROUP BY и HAVING на табличных данных',
        'WHERE фильтрует строки до группировки; HAVING фильтрует суммы групп. '
        f'После сортировки: {render(answer)}.', rng))

    query = ('SELECT u.id, COUNT(o.id) FROM users u LEFT JOIN orders o ON u.id=o.user_id' +
             (" AND o.status='paid'" if middle else '') + ' GROUP BY u.id ORDER BY u.id')
    answer = [[u['id'], sum(o['user_id'] == u['id'] and (not middle or o['status'] == 'paid') for o in orders)]
              for u in sorted(users, key=lambda u: u['id'])]
    ones = [[key, max(1, value)] for key, value in answer]
    rows.append(_question('sql-left-data', 'sql',
        f'SQLite. users = {render(users)}; orders = {render(orders)}.\n{query};\nКаковы строки [id, количество]?',
        {'users': users, 'orders': orders, 'middle': middle, 'query': query}, answer,
        [[], ones, [[key, value] for key, value in answer if value], [[key, 0] for key, _ in answer],
         [[key, value + 1] for key, value in answer]], 'LEFT JOIN, условие ON и COUNT(nullable)',
        'LEFT JOIN сохраняет каждого пользователя. COUNT(o.id) не считает NULL отсутствующего заказа. '
        f'Условие ON применяется при соединении. Результат: {render(answer)}.', rng))

    limit = rng.randint(1, 3)
    query = "SELECT id FROM orders" + (" WHERE status='paid'" if middle else '') + f' ORDER BY amount DESC, id ASC LIMIT {limit}'
    filtered = [o for o in orders if not middle or o['status'] == 'paid']
    ordered = sorted(filtered, key=lambda o: (-o['amount'], o['id']))
    answer = [o['id'] for o in ordered[:limit]]
    rows.append(_question('sql-order-data', 'sql',
        f'SQLite. orders = {render(orders)}.\n{query};\nКаков список id результата?',
        {'orders': orders, 'limit': limit, 'middle': middle, 'query': query}, answer,
        _lists([o['id'] for o in orders], answer), 'Стабильная сортировка, фильтр и LIMIT',
        f'Сначала фильтр, затем amount по убыванию и id по возрастанию при равенстве. '
        f'Первые {limit} строк: {render(answer)}.', rng))
    return rows


def _http(rng, middle):
    rows = []
    keys = rng.sample(range(10, 99), 3)
    bodies = rng.sample(range(100, 999), 3)
    events = [{'key': keys[0], 'body': bodies[0]}, {'key': keys[1], 'body': bodies[1]},
              {'key': keys[0], 'body': bodies[0]}]
    if middle:
        events += [{'key': keys[1], 'body': bodies[2]}, {'key': keys[2], 'body': bodies[2]}]
    rng.shuffle(events)
    saved, answer = {}, []
    for index, event in enumerate(events):
        key = event['key']
        if key not in saved:
            saved[key] = event['body']
        elif saved[key] != event['body']:
            answer.append(index + 1)
    # Junior selects replay requests; Middle diagnoses body/key conflicts.
    if not middle:
        seen = set()
        answer = []
        for index, event in enumerate(events):
            if event['key'] in seen:
                answer.append(index + 1)
            seen.add(event['key'])
    domain = list(range(1, len(events) + 1))
    rows.append(_question('http-idempotency-trace', 'http',
        'POST /offers. Область ключа — текущая компания, запись ключа и операция атомарны. '
        'Первый key создаёт операцию; тот же key/body возвращает сохранённый результат, '
        'тот же key с другим body даёт 409 без новой операции. Записи ключей не истекают. '
        f'Последовательные запросы: {render(events)}. Какие номера запросов '+
        ('получат 409?' if middle else 'вернут сохранённый результат?'),
        {'events': events, 'middle': middle}, answer, _lists(domain, answer),
        'Идемпотентность, replay и конфликт тела',
        f'Разберите key/body по очереди, сохраняя первое тело для ключа. Искомые номера: {render(answer)}.', rng))

    companies = rng.sample(['Альфа', 'Бета', 'Гамма', 'Дельта', 'Омега', 'Сигма'], 4)
    events = [{'company': companies[0], 'action': 'accept'}, {'company': companies[1], 'action': 'accept'},
              {'company': companies[0], 'action': 'revoke'}, {'company': companies[2], 'action': 'view'}]
    if middle:
        events.append({'company': companies[0], 'action': rng.choice(['accept', 'view'])})
        events.append({'company': companies[1], 'action': rng.choice(['revoke', 'view'])})
    grants = set()
    for event in events:
        if event['action'] == 'accept':
            grants.add(event['company'])
        elif event['action'] == 'revoke':
            grants.discard(event['company'])
    answer = sorted(grants)
    rows.append(_question('http-contact-revoke', 'http',
        'Изначально контакты скрыты всем. accept нового приглашения разрешает контакт только его компании; '
        'revoke отзывает все прежние разрешения этой компании; view ничего не разрешает. '
        f'События: {render(events)}. Какие компании получат контакт при следующем GET профиля? Список по алфавиту.',
        {'companies': companies, 'events': events}, answer, _lists(sorted(companies), answer),
        'Доступ компании и отзыв разрешения контакта',
        f'Разрешение хранится отдельно для каждой компании и проверяется заново на GET. После событий разрешены: {render(answer)}.', rng))

    initial = rng.randint(10, 89)
    conditions = [initial, initial, initial + 1, initial + rng.choice([0, 2])]
    if middle:
        rng.shuffle(conditions)
    revision, answer = initial, []
    for index, expected in enumerate(conditions):
        if expected == revision:
            answer.append(index + 1)
            revision += 1
    rows.append(_question('http-conditional-write', 'http',
        f'Ресурс имеет ETag "{initial}". PATCH меняет данные только при совпадении If-Match, '
        'после успеха числовой ETag увеличивается на 1; при несовпадении ответ 412 без изменения. '
        f'Последовательные If-Match: {render(conditions)}. Какие номера PATCH успешны?',
        {'initial': initial, 'conditions': conditions}, answer, _lists(list(range(1, 5)), answer),
        'Условная запись и потерянные обновления',
        f'Сравнивайте If-Match с текущей версией, увеличивая её только после успешной записи. Успешны: {render(answer)}.', rng))

    if _DEBIAS.get():
        rows.append(_object_scope_v6(rng))
        return rows
    companies = rng.sample(['Альфа', 'Бета', 'Гамма', 'Дельта', 'Омега', 'Сигма'], 4)
    owner, actor = rng.sample(companies, 2)
    actor = owner if rng.randrange(2) else actor
    role = rng.choice(['employer', 'candidate'])
    p = {'owner': owner, 'actor': actor, 'role': role, 'offer_id': rng.randint(100, 999)}
    own = actor == owner and role == 'employer'
    # Return concrete authorized resource id, rather than an unvarying generic rule.
    answer = [p['offer_id']] if own else []
    rows.append(_question('http-object-scope', 'http',
        f'GET /company/offers/{p["offer_id"]}. Приглашение принадлежит компании «{owner}». '
        f'Сессия: role={role}, company=«{actor}». Политика: только employer своей компании получает объект, '
        'чужой объект скрывается как 404, candidate получает 403. Каков список доступных id (ошибка означает [])?',
        p, answer, [[], [p['offer_id']], [p['offer_id'] + 1], [p['offer_id'], p['offer_id'] + 1]],
        'Проверка роли и принадлежности объекта',
        f'Проверяются обе предпосылки: employer и company == owner. Здесь доступный список: {render(answer)}.', rng))
    return rows


def _object_scope_v6(rng):
    """Два приглашения и сессия; исход (ничего / первое / второе / оба) выбирается равновероятно."""
    companies = rng.sample(['Альфа', 'Бета', 'Гамма', 'Дельта', 'Омега', 'Сигма'], 3)
    first_id, second_id = rng.sample(range(100, 999), 2)
    outcome = rng.randrange(4)                      # 0: [], 1: [первое], 2: [второе], 3: оба
    actor = companies[0]
    other = companies[1]
    owners = {0: (other, companies[2]), 1: (actor, other), 2: (other, actor), 3: (actor, actor)}[outcome]
    role = 'employer'
    if outcome == 0 and rng.randrange(2):
        role, owners = 'candidate', (actor, rng.choice([actor, other]))
    offers = [{'id': first_id, 'owner': owners[0]}, {'id': second_id, 'owner': owners[1]}]
    answer = [o['id'] for o in offers if role == 'employer' and o['owner'] == actor]
    p = {'offers': offers, 'role': role, 'actor': actor}
    return _question('http-object-scope', 'http',
        f'Сессия запрашивает по очереди GET /company/offers/{first_id} и GET /company/offers/{second_id}. '
        f'Приглашение {first_id} принадлежит компании «{owners[0]}», приглашение {second_id} — компании «{owners[1]}». '
        f'Сессия: role={role}, company=«{actor}». Политика: только employer своей компании получает объект, '
        'чужой объект скрывается как 404, candidate получает 403. Каков список id, запросы к которым вернут 200?',
        p, answer, [[], [first_id], [second_id], [first_id, second_id]],
        'Проверка роли и принадлежности объекта',
        'Проверяются обе предпосылки для каждого объекта: role=employer и company == owner. '
        f'Доступные id: {render(answer)}.', rng)


def _html(rng, middle):
    rows = []
    ids = [f'control-{v}' for v in rng.sample(range(10, 99), 4)]
    controls = [{'id': name, 'disabled': index == 1, 'tabindex': (-1 if index == 2 else 0)}
                for index, name in enumerate(ids)]
    if middle:
        controls[0]['tabindex'], controls[3]['tabindex'] = rng.sample([1, 2, 3], 2)
    else:
        rng.shuffle(controls)
    eligible = [c for c in controls if not c['disabled'] and c['tabindex'] >= 0]
    answer = [c['id'] for c in sorted(eligible, key=lambda c: (c['tabindex'] == 0, c['tabindex']))]
    markup = '\n'.join(f'<button id="{c["id"]}" tabindex="{c["tabindex"]}"'+
                       (' disabled' if c['disabled'] else '') + '>Действие</button>' for c in controls)
    rows.append(_question('html-tab-order', 'html',
        markup + '\nКаковы id последовательных остановок Tab? Начало перед первым элементом; других элементов нет.',
        {'controls': controls}, answer, _lists(ids, answer), 'Tab-порядок, disabled и tabindex',
        'Положительный tabindex идёт первым по возрастанию, затем 0 в DOM-порядке. '
        f'disabled и -1 исключены. Порядок: {render(answer)}.', rng))

    words = rng.sample(['Почта', 'Город', 'Телефон', 'Имя', 'Должность', 'Отдел'], 3)
    mode = rng.choice(['label', 'aria-label', 'aria-labelledby']) if middle else rng.choice(['label', 'aria-label'])
    p = {'words': words, 'mode': mode, 'input_id': f'field-{rng.randint(10, 99)}'}
    name = words[{'label': 0, 'aria-label': 1, 'aria-labelledby': 2}[mode]]
    aria = f' aria-label="{words[1]}"' if mode == 'aria-label' else ''
    if mode == 'aria-labelledby':
        aria = ' aria-labelledby="name-text"' + f' aria-label="{words[1]}"'
    markup = (f'<label for="{p["input_id"]}">{words[0]}</label>\n'
              f'<span id="name-text">{words[2]}</span>\n<input id="{p["input_id"]}"{aria} placeholder="Введите данные">')
    rows.append(_question('html-accessible-name', 'html', markup + '\nКакое доступное имя у input?',
        p, name, words + ['Введите данные', ''], 'Источники доступного имени и приоритет ARIA',
        f'В этом примере источник имени — {mode}; aria-labelledby имеет приоритет над aria-label, '
        f'а aria-label над label. Имя: {render(name)}.', rng))

    ids = [f'field-{v}' for v in rng.sample(range(10, 99), 4)]
    if _DEBIAS.get():
        bads = rng.sample(ids, 2 if middle else rng.choice([1, 2]))
        repaired = rng.choice(bads) if middle and rng.randrange(2) else None
        lines = []
        for index, name in enumerate(ids):
            label_for = name + '-typo' if name in bads else name
            aria = ' aria-label="Резервное имя"' if name == repaired else ''
            lines.append(f'<label for="{label_for}">Поле {index + 1}</label><input id="{name}"{aria}>')
        answer = [name for name in ids if name in bads and name != repaired]
        rows.append(_question('html-broken-label', 'html',
            '\n'.join(lines) + '\nУ каких input нет доступного имени? placeholder отсутствует; других источников имени нет.',
            {'ids': ids, 'bad': bads, 'repaired': repaired is not None}, answer, _lists(ids, answer),
            'Диагностика несовпадающего label for/id',
            f'for должен совпадать с id. ARIA может дать имя отдельно от label. Поля без имени: {render(answer)}.', rng))
    else:
        bad = rng.choice(ids)
        markup = '\n'.join(f'<label for="{name if name != bad else name + "-typo"}">Поле {index + 1}</label>'+
                           f'<input id="{name}">' for index, name in enumerate(ids))
        repaired = middle and bool(rng.randrange(2))
        if repaired:
            markup = markup.replace(f'<input id="{bad}">', f'<input id="{bad}" aria-label="Резервное имя">')
        answer = [] if repaired else [bad]
        rows.append(_question('html-broken-label', 'html',
            markup + '\nУ каких input нет доступного имени? placeholder отсутствует; других источников имени нет.',
            {'ids': ids, 'bad': bad, 'repaired': repaired}, answer, _lists(ids, answer),
            'Диагностика несовпадающего label for/id',
            f'for должен совпадать с id. ARIA может дать имя отдельно от label. Поля без имени: {render(answer)}.', rng))

    ids = [f'action-{v}' for v in rng.sample(range(10, 99), 4)]
    good_index = rng.randrange(4)
    p = {'ids': ids, 'native_index': good_index, 'middle': middle}
    markup = '\n'.join((f'<button id="{name}"'+(' type="button"' if middle else '')+'>Открыть</button>')
        if index == good_index else f'<div id="{name}" onclick="open()">Открыть</div>' for index, name in enumerate(ids))
    rows.append(_question('html-native-action', 'html', markup +
        '\nФрагмент расположен в форме. Обработчики клавиш у div отсутствуют. Какие id доступны клавиатурой '
        'как кнопки' + (' и не отправляют форму по умолчанию?' if middle else '?'),
        p, [ids[good_index]], _lists(ids, [ids[good_index]]),
        'Нативная кнопка, клавиатура и действие формы',
        'button имеет нативную клавиатурную семантику; onclick на div её не добавляет. '
        + ('type=button не отправляет форму. ' if middle else '') + f'Подходит {ids[good_index]}.', rng))
    return rows


def _testing(rng, middle):
    rows = []
    low, high = rng.randint(2, 9), rng.randint(15, 30)
    values = [low - 1, low, low + 1, high - 1, high, high + 1]
    inclusive = bool(rng.randrange(2)) if middle else True
    rng.shuffle(values)
    cases = [{'id': f'case-{v}', 'value': value} for v, value in zip(rng.sample(range(10, 99), 6), values)]
    answer = [c['id'] for c in cases if not low <= c['value'] <= high or (not inclusive and c['value'] == high)]
    rows.append(_question('qa-boundary-set', 'testing',
        f'Валидация принимает целые x: {low} <= x '+('<=' if inclusive else '<')+f' {high}. '
        f'Тесты: {render(cases)}. Какие id должны получить ошибку? Порядок списка исходный.',
        {'low': low, 'high': high, 'inclusive': inclusive, 'cases': cases}, answer,
        _lists([c['id'] for c in cases], answer), 'Набор граничных случаев и включительность',
        f'Проверяйте каждое значение по обеим границам. Ошибки: {render(answer)}. Значения рядом с границами проверяют off-by-one.', rng))

    company = rng.choice(['Альфа', 'Бета', 'Гамма'])
    other = rng.choice([c for c in ['Альфа', 'Бета', 'Гамма'] if c != company])
    cases = [{'id': f'case-{v}', 'role': role, 'company': organization}
             for v, (role, organization) in zip(rng.sample(range(10, 99), 4),
                 [('employer', company), ('employer', other), ('candidate', company), ('anonymous', None)])]
    rng.shuffle(cases)
    p = {'owner': company, 'cases': cases, 'middle': middle}
    if middle:
        answer = [[c['id'], 401 if c['role'] == 'anonymous' else 403 if c['role'] != 'employer'
                   else 200 if c['company'] == company else 404] for c in cases]
        wrong = [[[c['id'], status] for c in cases] for status in [200, 401, 403, 404]]
        if _DEBIAS.get():
            wrong = []   # мутации верной матрицы добавит _augment
    else:
        answer = [c['id'] for c in cases if c['role'] == 'employer' and c['company'] == company]
        wrong = _lists([c['id'] for c in cases], answer)
    rows.append(_question('qa-role-matrix', 'testing',
        f'GET приглашения компании «{company}». Политика: anonymous → 401; другая роль → 403; '
        f'employer чужой компании → 404; employer своей компании → 200. Тесты: {render(cases)}. '
        + ('Выберите полный список [id, ожидаемый HTTP status].' if middle else 'Какие id должны получить 200?'),
        p, answer, wrong, 'Матрица ролей и принадлежности объекта',
        f'Покрытие включает отсутствие сессии, неверную роль, чужой и свой объект. Ожидаемый результат: {render(answer)}.', rng))

    events = [{'id': f'event-{v}', 'action': action} for v, action in
              zip(rng.sample(range(10, 99), 4), rng.sample(['view', 'accept', 'decline', 'accept'], 4))]
    initial = rng.choice(['sent', 'viewed'])
    transitions = {'sent': {'view': 'viewed', 'accept': 'accepted', 'decline': 'declined'},
                   'viewed': {'accept': 'accepted', 'decline': 'declined'}, 'accepted': {}, 'declined': {}}
    if middle:
        transitions['accepted'] = {'view': 'accepted'}
        transitions['declined'] = {'view': 'declined'}
    state, answer = initial, []
    for event in events:
        next_state = transitions[state].get(event['action'])
        if next_state is None:
            answer.append(event['id'])
        else:
            state = next_state
    rows.append(_question('qa-transition-trace', 'testing',
        f'Приглашение изначально {initial}. Разрешённые переходы (state → action → state): {render(transitions)}. '
        f'События по очереди: {render(events)}. Недопустимое событие не меняет state. Какие id отклоняются?',
        {'initial': initial, 'transitions': transitions, 'events': events}, answer,
        _lists([e['id'] for e in events], answer), 'Тестирование переходов и повторных действий',
        f'После каждого успешного события используйте новое state; после ошибки сохраняйте его. Отклонены: {render(answer)}.', rng))

    minimum, maximum = rng.randint(10, 20), rng.randint(30, 50)
    payloads = [minimum, maximum, minimum - 1, maximum + 1, str(minimum), None]
    if middle:
        payloads += [True, minimum + .5]
    rng.shuffle(payloads)
    cases = [{'id': f'payload-{v}', 'value': value} for v, value in zip(rng.sample(range(10, 99), len(payloads)), payloads)]
    answer = [c['id'] for c in cases if type(c['value']) is not int or not minimum <= c['value'] <= maximum]
    rows.append(_question('qa-input-contract', 'testing',
        f'JSON API принимает amount: строго целое число от {minimum} до {maximum} включительно. '
        f'Преобразования строк/boolean нет, null запрещён. Тесты: {render(cases)}. Какие id должны получить 422?',
        {'minimum': minimum, 'maximum': maximum, 'cases': cases}, answer,
        _lists([c['id'] for c in cases], answer), 'Типы JSON, обязательность и диапазон',
        f'Сначала проверяется тип JSON, затем диапазон. Строка, boolean, null и дробь не являются разрешённым целым. Ошибки: {render(answer)}.', rng))
    return rows


# ---------------------------------------------------------------------------
# Дизайн (scenarios-v5/v6, добавлено 10 октября): вычисляемые задания по контрасту, сетке, шкале,
# зонам касания, метрикам юзабилити, закону Фиттса и эвристикам. Эталон — расчёт по формулам
# или заранее закреплённое соответствие «сценарий → эвристика»; визуальный вкус не оценивается.

_PALETTE = ['#000000', '#111827', '#1F2937', '#374151', '#4B5563', '#6B7280', '#9CA3AF', '#D1D5DB', '#F3F4F6',
            '#FFFFFF', '#1D4ED8', '#2563EB', '#60A5FA', '#B91C1C', '#EF4444', '#FCA5A5', '#047857', '#10B981',
            '#FDE68A', '#F59E0B', '#7C3AED', '#C4B5FD', '#FEF3C7', '#0F766E']


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground, background):
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _half_up(value):
    return int(value + 0.5)


def _clean_number(number):
    return int(number) if number == int(number) else number


def _ui(rng, middle):
    rows = []
    # Контраст WCAG: пары отбираются так, чтобы ни одна не лежала у порога 3:1 или 4.5:1.
    while True:
        pairs = []
        while len(pairs) < (5 if middle else 4):
            fg, bg = rng.sample(_PALETTE, 2)
            ratio = _contrast(fg, bg)
            if (all(abs(ratio - edge) > 0.25 for edge in (3.0, 4.5)) and ratio > 1.2
                    and (fg, bg) not in [(p['fg'], p['bg']) for p in pairs]):
                pairs.append({'id': len(pairs) + 1, 'fg': fg, 'bg': bg})
        ratios = {p['id']: _contrast(p['fg'], p['bg']) for p in pairs}
        answer = [i for i, r in ratios.items() if (3.0 <= r < 4.5 if middle else r >= 4.5)]
        if answer and len(answer) < len(pairs):
            break
    domain = [p['id'] for p in pairs]
    shown = '; '.join(f"{p['id']}) текст {p['fg']} на фоне {p['bg']}" for p in pairs)
    rows.append(_question('ui-contrast', 'ui',
        f'Пары цветов: {shown}. Контраст считается по формуле WCAG 2.x (относительная яркость sRGB). ' +
        ('Какие пары проходят AA только для крупного текста (контраст не ниже 3:1, но ниже 4.5:1)?' if middle
         else 'Какие пары проходят AA для обычного текста (контраст не ниже 4.5:1)?') + ' Номера по возрастанию.',
        {'pairs': pairs, 'middle': middle}, answer, _lists(domain, answer),
        'Расчёт контраста цвета по WCAG',
        'Относительная яркость L = 0.2126R + 0.7152G + 0.0722B после линеаризации sRGB; контраст = (L1 + 0.05) / (L2 + 0.05). ' +
        'Контрасты: ' + ', '.join(f'{i}: {r:.2f}' for i, r in ratios.items()) + f'. Подходят пары {render(answer)}.', rng))

    # Модульная сетка: ширина блока в k колонок с внутренними зазорами.
    columns = rng.choice([8, 12]) if middle else 12
    gutter = rng.choice([16, 20, 24])
    column = rng.choice([60, 64, 72, 80])
    padding = rng.choice([16, 24, 32]) if middle else 0
    width = columns * column + (columns - 1) * gutter + 2 * padding
    span = rng.randint(2, min(7, columns - 2))
    answer = span * column + (span - 1) * gutter
    wrong = [span * column, span * (column + gutter), span * column + (span + 1) * gutter, width * span // columns,
             (span - 1) * column + span * gutter, span * column + span * gutter - gutter // 2, answer + column, answer - gutter]
    rows.append(_question('ui-grid', 'ui',
        f'Макет шириной {width}px: {columns} равных колонок, зазор между соседними колонками {gutter}px' +
        (f', внешние поля {padding}px с каждой стороны.' if middle else ', внешних полей нет.') +
        f' Какова ширина блока (px), занимающего {span} подряд идущих колонок вместе с зазорами между ними?',
        {'width': width, 'columns': columns, 'gutter': gutter, 'padding': padding, 'span': span}, answer, wrong,
        'Расчёт модульной сетки',
        f'Ширина колонки = ({width} − {2 * padding} − {columns - 1}·{gutter}) / {columns} = {column}px. '
        f'Блок из {span} колонок: {span}·{column} + {span - 1}·{gutter} = {answer}px.', rng))

    # Модульная шкала размеров шрифта.
    base = rng.choice([14, 16, 18])
    ratio = rng.choice([1.2, 1.25, 1.5, 2.0])
    steps = rng.choice([2, 3])
    direction = -1 if middle and rng.randrange(2) else 1
    value = base * ratio ** (steps * direction)
    while abs(value - int(value) - 0.5) < 0.06:
        base += 1
        value = base * ratio ** (steps * direction)
    answer = _half_up(value)
    wrong = sorted({_half_up(base * ratio * steps), _half_up(base + steps * base * (ratio - 1)),
                    _half_up(base * ratio ** (steps - 1)), _half_up(base * ratio ** (steps + 1)),
                    _half_up(base * (1 + (ratio - 1) * steps * direction)),
                    _half_up(base / ratio ** steps if direction > 0 else base * ratio ** steps),
                    _half_up(base * ratio + base * direction)} - {answer})
    rows.append(_question('ui-type-scale', 'ui',
        f'Модульная шкала шрифта: базовый размер {base}px, коэффициент {ratio}. Каков размер шрифта (px, округление до целого) '
        f'на {steps}-м шаге ' + ('вниз' if direction < 0 else 'вверх') + ' от базового?',
        {'base': base, 'ratio': ratio, 'steps': steps, 'direction': direction}, answer, wrong,
        'Расчёт размеров модульной шкалы',
        f'Размер = {base} · {ratio}^({steps * direction}) = {value:.2f} → {answer}px. Шаги шкалы перемножаются, а не складываются.', rng))

    # Минимальный размер области касания (с учётом невидимого отступа).
    minimum = rng.choice([44, 48])
    while True:
        elements = []
        for index in range(5 if middle else 4):
            w, h = rng.choice([24, 32, 36, 40, 44, 48, 52]), rng.choice([24, 32, 36, 40, 44, 48, 52])
            pad = rng.choice([0, 4, 6, 8]) if middle else 0
            elements.append({'id': f'btn-{rng.randint(10, 99)}-{index}', 'w': w, 'h': h, 'pad': pad})
        answer = [e['id'] for e in elements if e['w'] + 2 * e['pad'] >= minimum and e['h'] + 2 * e['pad'] >= minimum]
        if answer and len(answer) < len(elements):
            break
    ids = [e['id'] for e in elements]
    shown = '; '.join(f"{e['id']}: {e['w']}×{e['h']}px" +
                      (f", область нажатия шире на {e['pad']}px с каждой стороны" if e['pad'] else '') for e in elements)
    rows.append(_question('ui-touch-target', 'ui',
        f'Требование: область нажатия не меньше {minimum}×{minimum}px по обеим сторонам. Элементы: {shown}. '
        'Какие элементы удовлетворяют требованию? Порядок исходный.',
        {'minimum': minimum, 'elements': elements}, answer, _lists(ids, answer),
        'Размер зоны касания',
        f'Проверяются обе стороны: ширина и высота с учётом отступа ({"w + 2·pad" if middle else "w и h"}). '
        f'Подходят: {render(answer)}.', rng))
    return rows


_HEURISTICS = ['Видимость состояния системы', 'Соответствие системы реальному миру', 'Контроль и свобода пользователя',
               'Согласованность и стандарты', 'Предотвращение ошибок', 'Распознавание вместо припоминания',
               'Гибкость и эффективность использования', 'Эстетика и минимализм',
               'Помощь в распознавании, диагностике и исправлении ошибок', 'Справка и документация']
_SCENARIOS = [
    (0, 'После нажатия «Оплатить» экран {n} секунд не меняется: нет индикатора загрузки и сообщения, поэтому пользователи нажимают кнопку повторно.'),
    (2, 'В мастере из {n} шагов нет кнопки «Назад» и отмены: выйти можно только закрыв вкладку и потеряв введённые данные.'),
    (3, 'В разделе настроек значок корзины означает «удалить», а в каталоге тот же значок означает «в корзину покупок»; сумма {n} в подтверждении то справа, то слева.'),
    (4, 'Кнопка «Удалить все {n} записей» расположена вплотную к кнопке «Сохранить» и сразу выполняет действие без подтверждения.'),
    (8, 'При ошибке показывается только код «0x{n}F», без объяснения причины и без подсказки, как исправить.'),
    (5, 'Чтобы применить фильтр, нужно ввести один из {n} кодов региона, но список кодов отсутствует на экране: пользователь вынужден помнить его наизусть.'),
    (1, 'Банковское приложение называет операцию «Сторнирование эквайринговой проводки #{n}» вместо понятного клиентам «Возврат платежа».'),
    (9, 'В сложном редакторе нет раздела помощи и подсказок: описание {n} команд доступно только в закрытом чате поддержки.'),
    (7, 'На главной странице {n} баннеров, шесть разных шрифтов и анимированный фон; основное действие трудно заметить.'),
    (6, 'Опытным пользователям для частой операции нужно {n} кликов: нет горячих клавиш, шаблонов и быстрых действий.'),
]


def _sus(answers):
    return sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers)) * 2.5


def _ux(rng, middle):
    rows = []
    # SUS: нечётные пункты — (ответ − 1), чётные — (5 − ответ), сумма · 2.5.
    testers = 3 if middle else 1
    sets = [[rng.randint(1, 5) for _ in range(10)] for _ in range(testers)]
    scores = [_sus(s) for s in sets]
    total = _clean_number(round(sum(scores) / testers, 1))
    wrong = [round(sum(sum(s) for s in sets) / testers * 2.5, 1),
             round(sum(sum(a - 1 for a in s) for s in sets) / testers * 2.5, 1),
             round(sum(sum(5 - a for a in s) for s in sets) / testers * 2.5, 1),
             round(sum(sum(s) / len(s) for s in sets) / testers * 20, 1),
             round(sum(sum(s) for s in sets) / testers, 1),
             round(_sus(sets[0]) + 2.5, 1), round(max(0, _sus(sets[0]) - 5), 1), round(_sus(sets[0]) + 7.5, 1)]
    shown = '; '.join(f'участник {i + 1}: {s}' for i, s in enumerate(sets))
    rows.append(_question('ux-sus', 'ux',
        f'Опрос SUS, 10 утверждений, шкала 1–5, порядок пунктов по списку. Ответы: {shown}. Нечётные пункты (1, 3, 5, 7, 9) '
        'положительные, чётные — отрицательные. ' +
        ('Какова средняя оценка SUS (0–100, округление до десятых)?' if middle else 'Какова оценка SUS (0–100)?'),
        {'responses': sets}, total, [_clean_number(w) for w in wrong if _clean_number(w) != total],
        'Расчёт оценки удобства по шкале SUS',
        'Положительные пункты дают (ответ − 1), отрицательные (5 − ответ); сумма умножается на 2.5. ' +
        f'Оценки: {", ".join(str(_clean_number(x)) for x in scores)}; итог: {total}.', rng))

    # Воронка: наибольшая доля потерь на переходе либо итоговая конверсия.
    names = ['Каталог', 'Карточка товара', 'Корзина', 'Доставка', 'Оплата']
    while True:
        counts = [rng.randrange(900, 1300, 50)]
        rates = [rng.choice([0.55, 0.6, 0.7]), rng.choice([0.4, 0.5, 0.75]), rng.choice([0.8, 0.85, 0.9]), rng.choice([0.3, 0.65, 0.95])]
        rng.shuffle(rates)
        for rate in rates:
            counts.append(round(counts[-1] * rate))
        drops = [(counts[i] - counts[i + 1]) / counts[i] for i in range(4)]
        if sorted(drops)[-1] - sorted(drops)[-2] >= 0.05:
            break
    labels = [f'{names[i]} → {names[i + 1]}' for i in range(4)]
    if middle:
        answer = _clean_number(round(counts[-1] / counts[0] * 100, 1))
        wrong = [round(counts[-1] / counts[-2] * 100, 1), round(sum(1 - d for d in drops) / 4 * 100, 1),
                 round((1 - drops[0]) * 100, 1), round((counts[0] - counts[-1]) / counts[0] * 100, 1),
                 round(sum(drops) / 4 * 100, 1), round(counts[-1] / counts[1] * 100, 1)]
        wrong = [_clean_number(w) for w in wrong if _clean_number(w) != answer]
        question = 'Какова конверсия из первого шага в последний, % (округление до десятых)?'
        reason = (f'Конверсия = {counts[-1]} / {counts[0]} · 100 = {answer}%. '
                  'Берётся доля дошедших до последнего шага от числа пользователей на первом шаге.')
    else:
        top = max(range(4), key=lambda i: drops[i])
        answer = labels[top]
        wrong = [l for i, l in enumerate(labels) if i != top] + ['Потери на всех переходах одинаковы',
                                                                'Нельзя определить без данных о выручке']
        question = 'На каком переходе теряется наибольшая доля пользователей?'
        reason = ('Доля потерь = (было − стало) / было: ' +
                  ', '.join(f'{l}: {d * 100:.1f}%' for l, d in zip(labels, drops)) + f'. Максимум: {answer}.')
    shown = ', '.join(f'{n}: {c}' for n, c in zip(names, counts))
    rows.append(_question('ux-funnel', 'ux', f'Число пользователей по шагам воронки: {shown}. ' + question,
        {'steps': names, 'counts': counts, 'middle': middle}, answer, wrong, 'Анализ воронки по шагам', reason, rng))

    # Закон Фиттса: индекс сложности и время перемещения.
    bits = rng.choice([2, 3, 4])
    width = rng.choice([20, 25, 40, 50])
    distance = width * (2 ** bits - 1)
    a, b = rng.choice([100, 200]), rng.choice([100, 150, 200])
    if middle:
        answer = a + b * bits
        wrong = [a + b * (2 ** bits - 1), b * bits, a + b * (bits - 1), a + b * (bits + 1), a + b * 2 ** bits,
                 a * bits + b, a + b * bits // 2]
        question = f'Время перемещения по модели Фиттса MT = a + b·ID, где a = {a} мс, b = {b} мс/бит. Каково MT (мс)?'
        reason = f'ID = log2(D/W + 1) = log2({distance}/{width} + 1) = {bits} бит; MT = {a} + {b}·{bits} = {answer} мс.'
    else:
        answer = bits
        wrong = [bits - 1, bits + 1, bits + 2, 2 ** bits - 1, 2 ** bits, bits * 2, max(1, bits - 2)]
        question = 'Каков индекс сложности ID = log2(D/W + 1) (бит)?'
        reason = (f'D/W = {distance}/{width} = {2 ** bits - 1}; ID = log2({2 ** bits}) = {bits} бит. '
                  'Сложность растёт с логарифмом отношения расстояния к ширине цели.')
    rows.append(_question('ux-fitts', 'ux',
        f'Кнопка шириной W = {width}px расположена на расстоянии D = {distance}px от курсора вдоль оси движения. ' + question,
        {'distance': distance, 'width': width, 'a': a, 'b': b, 'middle': middle}, answer,
        [w for w in dict.fromkeys(wrong) if w != answer], 'Закон Фиттса', reason, rng))

    # Эвристики Нильсена: заранее закреплённое соответствие сценария нарушению.
    chosen = rng.randrange(len(_SCENARIOS))
    index, template = _SCENARIOS[chosen]
    number = rng.choice([3, 5, 7, 12, 14, 20, 30])
    others = [h for i, h in enumerate(_HEURISTICS) if i != index]
    rows.append(_question('ux-heuristic', 'ux',
        f'Сценарий: {template.format(n=number)} Какая из эвристик юзабилити Нильсена нарушена в первую очередь?',
        {'scenario': chosen, 'number': number}, _HEURISTICS[index], others, 'Эвристики юзабилити Нильсена',
        f'Сценарий соответствует эвристике «{_HEURISTICS[index]}»: именно её требование нарушено в описанной ситуации.', rng))
    return rows


def scenario_questions(seed, grade, specialization, debias=False):
    if specialization not in {'backend', 'frontend', 'qa', 'design'} or grade not in {'junior', 'middle'}:
        raise ValueError('unsupported_blueprint')
    token = _DEBIAS.set(bool(debias))
    try:
        return _scenario_rows(seed, grade, specialization)
    finally:
        _DEBIAS.reset(token)


def _scenario_rows(seed, grade, specialization):
    rng = random.Random(seed)
    middle = grade == 'middle'
    groups = {'backend': (_python, _sql, _http), 'frontend': (_javascript, _html, _http),
              'qa': (_testing, _sql, _http), 'design': (_ux, _ui, _html)}[specialization]
    rows = []
    for generate in groups:
        rows.extend(generate(random.Random(rng.getrandbits(64)), middle))
    rng.shuffle(rows)
    return rows
