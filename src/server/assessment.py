"""Версионируемые параметризованные формы. Не психометрическая аттестация."""
import random


def legacy_questions(seed: int, grade: str):
    rng = random.Random(seed)
    n = rng.randint(3, 9)
    if grade == "junior":
        rows = [
            ("python-range", "python", f"Сколько элементов в list(range({n}))?", [str(n), str(n+1), str(n-1)], str(n)),
            ("python-none", "python", "Как проверить, что value равен None?", ["value is None", "value == 0", "not value"], "value is None"),
            ("sql-group", "sql", "Что используют для подсчёта строк по каждой группе?", ["GROUP BY и COUNT(*)", "ORDER BY и LIMIT", "DISTINCT и OFFSET"], "GROUP BY и COUNT(*)"),
            ("sql-null", "sql", "Как выбрать строки с пустым nullable полем email?", ["email IS NULL", "email = NULL", "email = ''"], "email IS NULL"),
        ]
    else:
        rows = [
            ("python-default", "python", "Почему изменяемый default-аргумент списка опасен?", ["Один объект используется между вызовами", "Список нельзя менять", "Python копирует его при каждом вызове"], "Один объект используется между вызовами"),
            ("python-retry", "python", "Что предотвращает дубли при повторной отправке одной операции?", ["Идемпотентный ключ и уникальное ограничение", "Новый UUID на каждом повторе", "Проверка только в браузере"], "Идемпотентный ключ и уникальное ограничение"),
            ("sql-lock", "sql", "Как защитить read-modify-write строки внутри транзакции?", ["SELECT FOR UPDATE", "Обычный SELECT вне транзакции", "ORDER BY"], "SELECT FOR UPDATE"),
            ("sql-index", "sql", "Что проверяют перед добавлением индекса для запроса?", ["План выполнения и характер нагрузки", "Только длину имени таблицы", "Цвет интерфейса"], "План выполнения и характер нагрузки"),
        ]
    result = []
    for key, skill, title, options, answer in rows:
        rng.shuffle(options)
        result.append(dict(id=key, skill=skill, title=title, options=options, answer=answer))
    return result


SCENARIO_VERSIONS = {'scenarios-v5', 'scenarios-v6'}
VERSION = 'scenarios-v6'
CATALOG = {
    'backend': {'label': 'Backend / Python', 'skills': ['python', 'sql', 'http']},
    'frontend': {'label': 'Frontend / JavaScript', 'skills': ['javascript', 'html', 'http']},
    'qa': {'label': 'QA / тестирование', 'skills': ['testing', 'sql', 'http']},
    'design': {'label': 'UI/UX дизайн', 'skills': ['ux', 'ui', 'html']},
}


def round_questions(seed, grade, specialization='backend', version=VERSION):
    if version == 'demo-backend-v1':
        return legacy_questions(seed, grade)
    if version not in SCENARIO_VERSIONS | {'families-v2', 'families-v3', 'families-v4'} or specialization not in CATALOG or grade not in {'junior', 'middle'}:
        raise ValueError('unsupported_blueprint')
    if specialization == 'design' and version not in SCENARIO_VERSIONS:
        # Дизайн появился в сценарных формах; прежние семейства для него не создавались.
        raise ValueError('unsupported_blueprint')
    if version in SCENARIO_VERSIONS:
        from .assessment_scenarios import scenario_questions
        return scenario_questions(seed, grade, specialization, debias=version == 'scenarios-v6')
    if version == 'families-v4':
        return parameterized_round(seed, grade, specialization)
    rng = random.Random(seed)
    n, k = rng.randint(6, 18), rng.randint(2, 5)
    # Одни семейства и веса в каждой форме; параметры и порядок различаются.
    # Middle добавляет вложенную операцию/состояние, диапазоны одинаковы для всех.
    middle = grade == 'middle'
    extra_names = 2 if version == 'families-v2' else min(2, n-k)
    py = [
        ('python-range', 'python', f'Сколько элементов в list(range(0, {n}, {k}))?', str(len(range(0, n, k)))),
        ('python-state', 'python', f'Список xs = [{n}, {k}]. '+('ys = xs; ys.append(0). Какова длина xs?' if middle else 'xs.append(0). Какова сумма xs?'), '3' if middle else str(n+k)),
    ]
    js = [
        ('js-map', 'javascript', f'Чему равна сумма [{n}, {k}]'+(f'.filter(x => x > {k})' if middle else '')+'.map(x => x * 2)?', str(n*2 if middle else (n+k)*2)),
        ('js-filter', 'javascript', f'Сколько элементов останется в Array.from({{length: {n}}}, (_, i) => i).filter(i => i % {k} === 0'+(' && i > 0' if middle else '')+')?', str(len(range(0,n,k))-(1 if middle else 0))),
    ]
    sql = [
        ('sql-count', 'sql', f'В таблице {n} строк, у {k} строк email IS NULL. Что вернёт SELECT COUNT(email) FROM users?', str(n-k)),
        ('sql-join', 'sql', f'В users {n} пользователей. У {k} есть по 2 заказа, у остальных нет. Сколько строк даст '+('LEFT JOIN orders' if middle else 'INNER JOIN orders')+' по user_id?', str(n+k if middle else k*2)),
    ]
    html = [
        ('html-focus', 'html', f'На странице {n} кнопок. {k} из них имеют disabled. '+('Ещё одна активная кнопка имеет tabindex=-1. ' if middle else '')+'Сколько кнопок доступны в обычном Tab-порядке?', str(n-k-(1 if middle else 0))),
        ('html-label', 'html', f'Форма содержит {n} input с уникальными id. Только {k} label имеют корректный for. '+(f'Ещё {extra_names} разных input без label имеют aria-labelledby с существующим текстом. Сколько input остаются без доступного имени?' if middle else 'Сколько input не имеют связи с label?'), str(n-k-(extra_names if middle else 0))),
    ]
    testing = [
        ('test-boundaries', 'testing', f'Поле принимает целые значения от {k} до {n} включительно. '+('Проверены '+str(k-1)+', '+str(k)+', '+str(n)+', '+str(n+1)+'. Сколько из этих проверок должны завершиться ошибкой?' if middle else 'Какое минимальное недопустимое значение сразу после верхней границы?'), '2' if middle else str(n+1)),
        ('test-cases', 'testing', f'Есть {k} браузеров и {n} независимых наборов входных данных. '+('Для каждого проверяем две роли. ' if middle else '')+'Сколько проверок нужно для полного произведения?', str(n*k*(2 if middle else 1))),
    ]
    http = [
        ('http-retry', 'http', f'Клиент отправил один POST с одним Idempotency-Key {n} раз. Сколько операций допустимо создать?', '1'),
        ('http-access', 'http', f'{n} компаний просматривают кандидата. Кандидат разрешил контакт ровно {k} компаниям. Сколько компаний должны получить ответ без контакта?', str(n-k)),
    ]
    rows = {'backend': py+sql+http, 'frontend': js+html+http, 'qa': testing+sql+http}[specialization]
    result=[]
    for key, skill, title, answer in rows:
        value=int(answer)
        offsets=rng.sample([i for i in range(-5,6) if i and value+i>=0],3)
        options=[answer]+[str(value+offset) for offset in offsets]
        rng.shuffle(options)
        result.append({'id':key,'family':key,'skill':skill,'title':title,'options':options,'answer':answer})
    rng.shuffle(result)
    return result


def parameterized_round(seed, grade, specialization):
    """Содержательные параметры каждой семьи независимы от остальных.

    parameters содержит только данные из условия, не эталон или seed.
    Старые генераторы выше сохранены для попыток без question_form snapshot.
    """
    rng = random.Random(seed)
    middle = grade == 'middle'
    families = {
        'backend': ('python-range', 'python-state', 'sql-count', 'sql-join', 'http-retry', 'http-access'),
        'frontend': ('js-map', 'js-filter', 'html-focus', 'html-label', 'http-retry', 'http-access'),
        'qa': ('test-boundaries', 'test-cases', 'sql-count', 'sql-join', 'http-retry', 'http-access'),
    }
    result = []
    for family in families[specialization]:
        # Отдельный поток не позволяет общему n/k совпасть сразу в ряде ответов.
        local = random.Random(rng.getrandbits(64))
        n, k = local.randint(12, 40), local.randint(2, 8)
        params = {'n': n, 'k': k}
        if family == 'python-range':
            skill = 'python'
            params['start'] = local.randint(0, k - 1) if middle else 0
            title = f"Сколько элементов в list(range({params['start']}, {n}, {k}))?"
            answer = len(range(params['start'], n, k))
        elif family == 'python-state':
            skill = 'python'
            values = [local.randint(1, 12) for _ in range(local.randint(2, 6) if middle else 2)]
            appended = [local.randint(0, 12) for _ in range(local.randint(1, 4) if middle else 1)]
            params = {'values': values, 'appended': appended}
            title = f'Список xs = {values}. '
            if middle:
                title += f'ys = xs; ys.extend({appended}). Какова длина xs?'
                answer = len(values) + len(appended)
            else:
                title += f'xs.append({appended[0]}). Какова сумма xs?'
                answer = sum(values) + appended[0]
        elif family == 'js-map':
            skill = 'javascript'
            title = f'Чему равна сумма [{n}, {k}]' + (f'.filter(x => x > {k})' if middle else '') + '.map(x => x * 2)?'
            answer = n * 2 if middle else (n + k) * 2
        elif family == 'js-filter':
            skill = 'javascript'
            title = f'Сколько элементов останется в Array.from({{length: {n}}}, (_, i) => i).filter(i => i % {k} === 0' + (' && i > 0' if middle else '') + ')?'
            answer = len(range(0, n, k)) - (1 if middle else 0)
        elif family == 'sql-count':
            skill = 'sql'
            title = f'В таблице {n} строк, у {k} строк email IS NULL. Что вернёт SELECT COUNT(email) FROM users?'
            answer = n - k
        elif family == 'sql-join':
            skill = 'sql'
            params['orders_per_user'] = local.randint(2, 5)
            count = params['orders_per_user']
            title = f'В users {n} пользователей. У {k} есть по {count} заказа, у остальных нет. Сколько строк даст ' + ('LEFT JOIN orders' if middle else 'INNER JOIN orders') + ' по user_id?'
            answer = n - k + k * count if middle else k * count
        elif family == 'html-focus':
            skill = 'html'
            params['tab_excluded'] = local.randint(1, 4) if middle else 0
            excluded = params['tab_excluded']
            title = f'На странице {n} кнопок. {k} из них имеют disabled. ' + (f'Число дополнительных активных кнопок с tabindex=-1: {excluded}. ' if middle else '') + 'Сколько кнопок доступны в обычном Tab-порядке?'
            answer = n - k - excluded
        elif family == 'html-label':
            skill = 'html'
            params['aria_named'] = local.randint(1, 4) if middle else 0
            named = params['aria_named']
            title = f'Форма содержит {n} input с уникальными id. Только {k} label имеют корректный for. ' + (f'Ещё {named} разных input без label имеют aria-labelledby с существующим текстом. Сколько input остаются без доступного имени?' if middle else 'Сколько input не имеют связи с label?')
            answer = n - k - named
        elif family == 'test-boundaries':
            skill = 'testing'
            title = f'Поле принимает целые значения от {k} до {n} включительно. '
            if middle:
                invalid = local.sample([k - 2, k - 1, n + 1, n + 2], local.randint(1, 4))
                valid = local.sample([k, k + 1, n - 1, n], local.randint(2, 4))
                params['checked_values'] = sorted(invalid + valid)
                title += f"Проверены значения {params['checked_values']}. Сколько проверок должны завершиться ошибкой?"
                answer = len(invalid)
            else:
                title += 'Какое минимальное недопустимое значение сразу после верхней границы?'
                answer = n + 1
        elif family == 'test-cases':
            skill = 'testing'
            params['roles'] = local.randint(2, 4) if middle else 1
            title = f'Есть {k} браузеров и {n} независимых наборов входных данных. ' + (f"Число ролей для каждой комбинации: {params['roles']}. " if middle else '') + 'Сколько проверок нужно для полного произведения?'
            answer = n * k * params['roles']
        elif family == 'http-retry':
            skill = 'http'
            keys, repetitions = local.randint(2, 16), local.randint(2, 8)
            fresh = local.randint(1, 6) if middle else 0
            params = {'distinct_keys': keys, 'repetitions': repetitions, 'fresh_keys': fresh}
            title = f'Клиент создаёт {keys} разных операций POST, у каждой свой Idempotency-Key. Каждый запрос повторён {repetitions} раз с тем же ключом и телом. '
            if middle:
                title += f'Затем отправлены ещё {fresh} операций с новыми уникальными ключами. '
            title += 'Сервер корректно поддерживает идемпотентность, запросы успешны. Сколько операций создано всего?'
            answer = keys + fresh
        else:  # http-access
            skill = 'http'
            title = f'{n} компаний просматривают кандидата. Кандидат разрешил контакт ровно {k} компаниям. Сколько компаний должны получить ответ без контакта?'
            answer = n - k
        offsets = local.sample([i for i in range(-5, 6) if i and answer + i >= 0], 3)
        options = [str(answer)] + [str(answer + offset) for offset in offsets]
        local.shuffle(options)
        result.append({'id': family, 'family': family, 'skill': skill, 'title': title,
                       'parameters': params, 'options': options, 'answer': str(answer)})
    rng.shuffle(result)
    return result


def questions(seed, grade, specialization='backend', version=VERSION):
    if version not in {'families-v4', 'families-v3'}:
        return round_questions(seed,grade,specialization,version)
    # Два раунда одного blueprint дают 12 равновесных заданий и различимые пороги.
    form=[]
    for index,round_seed in enumerate((seed,seed^0x5F3759DF)):
        for row in round_questions(round_seed,grade,specialization,version):
            form.append({**row,'id':str(index+1)+'-'+row['id']})
    random.Random(seed^0x1321).shuffle(form)
    return form


def public_question_form(form):
    """Явная проекция сохранённой формы; новые private поля не попадут в API."""
    # Интерфейсу нужны только показанные условия и варианты. Внутренний тип
    # задачи и структурированные параметры остаются в серверном снимке.
    allowed = ('id', 'skill', 'title', 'options')
    return [{key: row[key] for key in allowed if key in row} for row in form]


def public_questions(seed, grade, specialization='backend', version=VERSION):
    return public_question_form(questions(seed,grade,specialization,version))


def evaluate(seed, grade, answers, specialization='backend', version=VERSION, form=None):
    rows=form if form is not None else questions(seed,grade,specialization,version)
    allowed={q['id'] for q in rows}
    if not set(answers)<=allowed or any(answer not in next(q['options'] for q in rows if q['id']==key) for key,answer in answers.items()):
        raise ValueError('Ответы не соответствуют выданной форме')
    correct=sum(answers.get(q['id'])==q['answer'] for q in rows)
    score=round(100*correct/len(rows),2)
    breakdown=[]
    for skill in sorted({q['skill'] for q in rows}):
        group=[q for q in rows if q['skill']==skill]
        passed=sum(answers.get(q['id'])==q['answer'] for q in group)
        breakdown.append({'skill':skill,'correct':passed,'total':len(group),'score':round(100*passed/len(group),2)})
    return {'score':score,'skills':[b['skill'] for b in breakdown if b['score']>=50],
            'passed':score >= (70 if grade=='junior' else 80),'breakdown':breakdown,
            'version':version,'demo':True,'limitation':(
                'Авторские сценарии с одинаковой матрицей навыков и весами. Профессиональная сложность Junior/Middle не калибрована; экспертная оценка и независимый человеческий пилот ещё не проведены.'
                if version in SCENARIO_VERSIONS else
                'Параметризованные семейства с одинаковой матрицей навыков. Экспертная калибровка и независимый пилот ещё не проведены.')}
