"""Учебный разбор завершённой оценки по её сохранённой форме.

Вызывающий код проверяет завершение и владельца попытки до вызова feedback:
отчёт содержит эталоны. Здесь нет генератора, seed, записи результата или
изменения грейда. Это разбор небольшой формы, не сертификация навыков.
"""
from collections import defaultdict


_TOPICS = {
    'python-range': 'Границы range и шаг последовательности',
    'python-state': 'Изменение списка, ссылки на объект, append и extend',
    'js-map': 'Порядок filter и map, преобразование и сумма массива',
    'js-filter': 'Предикат filter, остаток от деления и границы индексов',
    'sql-count': 'COUNT(column), COUNT(*) и NULL',
    'sql-join': 'Число строк INNER JOIN и LEFT JOIN при связи один ко многим',
    'html-focus': 'Порядок Tab, disabled и tabindex=-1',
    'html-label': 'Доступное имя поля, label for и aria-labelledby',
    'test-boundaries': 'Граничные значения и включительные пределы',
    'test-cases': 'Полное произведение браузеров, данных и ролей',
    'http-retry': 'Idempotency-Key, повтор запроса и новая операция',
    'http-access': 'Разрешение контакта отдельно для каждой компании',
}


def _integer(params, name, minimum=0):
    value = params[name]
    if type(value) is not int or value < minimum:
        raise ValueError('Некорректный параметр сохранённой формы')
    return value


def _integers(params, name, nonnegative=False):
    values = params[name]
    if not isinstance(values, list) or any(type(v) is not int for v in values):
        raise ValueError('Некорректный список параметров')
    if nonnegative and any(v < 0 for v in values):
        raise ValueError('Некорректный список параметров')
    return values


def _reason(family, params, middle):
    """Получает расчёт только из явных параметров; код условия не исполняет."""
    if family == 'python-state':
        values = _integers(params, 'values', nonnegative=True)
        appended = _integers(params, 'appended', nonnegative=True)
        if not values or not appended or (not middle and len(appended) != 1):
            raise ValueError('Неполные параметры списка')
        if middle:
            answer = len(values) + len(appended)
            text = (f'xs содержит {values}; число элементов: {len(values)}. ys = xs связывает '
                    f'два имени с одним списком. extend({appended}) добавляет '
                    f'все эти элементы и в xs; их количество: {len(appended)}. Длина: '
                    f'{len(values)} + {len(appended)} = {answer}.')
        else:
            answer = sum(values) + appended[0]
            text = (f'append({appended[0]}) добавляет один элемент к {values}. '
                    f'Сумма исходных элементов {sum(values)}; после добавления '
                    f'{sum(values)} + {appended[0]} = {answer}.')
        return answer, text
    if family == 'http-retry':
        keys = _integer(params, 'distinct_keys', 1)
        repeats = _integer(params, 'repetitions', 1)
        fresh = _integer(params, 'fresh_keys')
        if not middle and fresh:
            raise ValueError('Несогласованные параметры повторов')
        answer = keys + fresh
        return answer, (f'Для {keys} разных ключей создаётся по одной операции. '
                        f'{repeats} повторов с тем же ключом и телом возвращают '
                        f'результат исходной операции. Новых ключей: {fresh}. '
                        f'Всего операций: {keys} + {fresh} = {answer}.')
    n, k = _integer(params, 'n', 1), _integer(params, 'k', 1)
    if k >= n:
        raise ValueError('Несогласованные границы')
    if family == 'python-range':
        start = _integer(params, 'start')
        if start >= n:
            raise ValueError('Некорректное начало range')
        answer = (n - start + k - 1) // k
        last = start + (answer - 1) * k
        return answer, (f'range({start}, {n}, {k}) включает начало {start}, '
                        f'но исключает верхнюю границу {n}. Последнее значение '
                        f'{last}; следующий шаг даёт {last + k}, уже не меньше '
                        f'{n}. Число элементов: ({last} − {start}) / {k} + 1 = {answer}.')
    if family == 'js-map':
        kept = [n] if middle else [n, k]
        mapped = [value * 2 for value in kept]
        answer = sum(mapped)
        filtering = (f'filter(x => x > {k}) оставляет {kept}, поскольку {k} '
                     f'не больше самого себя. ' if middle else f'Исходный массив [{n}, {k}]. ')
        return answer, filtering + f'map(x => x * 2) даёт {mapped}. Сумма: {answer}.'
    if family == 'js-filter':
        first = k if middle else 0
        count = (n - 1) // k + (0 if middle else 1)
        last = ((n - 1) // k) * k
        extra = ' Условие i > 0 исключает ноль.' if middle else ' Ноль проходит условие остатка.'
        return count, (f'Индексы массива длины {n}: от 0 до {n - 1}. '
                       f'i % {k} === 0 оставляет кратные {k}.{extra} '
                       f'Остаются значения от {first} до {last} с шагом {k}, '
                       f'всего {count}.')
    if family == 'sql-count':
        answer = n - k
        return answer, (f'COUNT(email) учитывает только значения, отличные от NULL. '
                        f'Из {n} строк исключаются {k} строк с NULL: '
                        f'{n} − {k} = {answer}. COUNT(*) учитывал бы все {n} строк.')
    if family == 'sql-join':
        orders = _integer(params, 'orders_per_user', 1)
        matched = k * orders
        if middle:
            answer = matched + n - k
            text = (f'LEFT JOIN даёт {k} × {orders} = {matched} строк с заказами. '
                    f'Остальные {n} − {k} = {n - k} пользователей сохраняются '
                    f'по одной строке с NULL в полях заказа. Всего: '
                    f'{matched} + {n - k} = {answer}.')
        else:
            answer = matched
            text = (f'INNER JOIN сохраняет только пользователей с заказами. '
                    f'Каждый из {k} пользователей даёт {orders} строк: '
                    f'{k} × {orders} = {answer}. Пользователи без заказов '
                    f'({n - k}) строк не добавляют.')
        return answer, text
    if family in {'html-focus', 'html-label'}:
        name = 'tab_excluded' if family == 'html-focus' else 'aria_named'
        extra = _integer(params, name)
        if k + extra > n or (not middle and extra):
            raise ValueError('Несогласованные параметры HTML')
        answer = n - k - extra
        if family == 'html-focus':
            text = (f'Из {n} кнопок {k} disabled не участвуют в обычном Tab-порядке. '
                    f'Ещё {extra} активных кнопок с tabindex=-1 исключены из '
                    f'последовательного перехода Tab; их можно фокусировать программно. '
                    f'Доступны: {n} − {k} − {extra} = {answer}.')
        else:
            ending = 'без доступного имени' if middle else 'без связи с label'
            text = (f'Корректный for связывает {k} label с input по id из {n} полей. '
                    f'aria-labelledby даёт доступное имя ещё {extra} отдельным '
                    f'полям через указанный существующий текст. '
                    f'Остаются {ending}: {n} − {k} − {extra} = {answer}.')
        return answer, text
    if family == 'test-boundaries':
        if middle:
            checked = _integers(params, 'checked_values')
            invalid = [value for value in checked if value < k or value > n]
            return len(invalid), (f'Допустимы целые значения от {k} до {n} включительно. '
                                  f'В проверках {checked} вне диапазона находятся '
                                  f'{invalid}. Эти проверки должны вернуть ошибку; '
                                  f'их количество: {len(invalid)}. Сами границы допустимы.')
        return n + 1, (f'Верхняя граница {n} включена в допустимый диапазон '
                       f'[{k}, {n}]. Следующее целое значение {n} + 1 = {n + 1} '
                       f'— минимальное недопустимое сразу после неё.')
    if family == 'test-cases':
        roles = _integer(params, 'roles', 1)
        if not middle and roles != 1:
            raise ValueError('Несогласованные параметры ролей')
        answer = n * k * roles
        return answer, (f'Для каждого из {k} браузеров нужны все {n} наборов '
                        f'входных данных и {roles} ролей. В полном произведении '
                        f'числа комбинаций перемножаются: '
                        f'{k} × {n} × {roles} = {answer}.')
    if family == 'http-access':
        answer = n - k
        return answer, (f'Разрешение контакта действует отдельно для каждой компании. '
                        f'Из {n} компаний контакт разрешён {k}. Остальным '
                        f'{n} − {k} = {answer} компаниям нужно вернуть ответ '
                        f'без контакта; просмотр профиля разрешение не заменяет.')
    raise ValueError('Неизвестное семейство')


def _explanation(row, grade, version):
    answer = row['answer']
    fallback = (f'Эталон сохранённой формы: {answer}. Подробный разбор для этого '
                f'задания недоступен: версия, условие или параметры не позволяют '
                f'надёжно восстановить ход решения. Эталон и результат попытки сохранены.')
    if version in {'scenarios-v5', 'scenarios-v6'}:
        reason = row.get('explanation')
        if isinstance(reason, str) and reason.strip() and row.get('explanation_answer') == answer:
            return reason + f' Эталон сохранённой формы: {answer}.'
        return fallback
    if (version != 'families-v4' or row.get('family') not in _TOPICS
            or not isinstance(row.get('parameters'), dict)
            or not isinstance(row.get('title'), str) or not row['title'].strip()):
        return fallback
    try:
        derived, reason = _reason(row['family'], row['parameters'], grade == 'middle')
    except (KeyError, TypeError, ValueError):
        return fallback
    # Даже если параметры противоречат старому эталону, история авторитетна.
    if str(derived) != answer:
        return fallback
    return reason + f' Эталон сохранённой формы: {answer}.'


def feedback(form, answers, grade, version):
    """Возвращает учебный отчёт; нужны исходная приватная форма и ответы.

    needed_correct — минимальное ОБЩЕЕ число правильных для порога, а не
    число дополнительных ответов. strong/review используют 75% по навыку;
    это учебная подсказка, отдельная от действующего подтверждения грейда.
    Отсутствующий ответ считается unanswered и остаётся в знаменателе.
    """
    if grade not in {'junior', 'middle'}:
        raise ValueError('Неизвестный грейд')
    if not form or any(not isinstance(row.get('answer'), str) for row in form):
        raise ValueError('Для отчёта нужна сохранённая форма с эталонами')
    ids = {row['id'] for row in form}
    if len(ids) != len(form) or not set(answers) <= ids:
        raise ValueError('Ответы не соответствуют сохранённой форме')
    if any(answers[row['id']] not in row['options'] for row in form if row['id'] in answers):
        raise ValueError('Ответы не соответствуют сохранённой форме')
    rows, groups = [], defaultdict(list)
    for question in form:
        selected = answers.get(question['id'])
        status = ('unanswered' if selected is None else
                  'correct' if selected == question['answer'] else 'incorrect')
        row = {'id': question['id'], 'skill': question['skill'], 'status': status,
               'selected_answer': selected, 'correct_answer': question['answer'],
               'explanation': _explanation(question, grade, version)}
        rows.append(row)
        groups[question['skill']].append((question, status))
    skills = []
    for skill in sorted(groups):
        group = groups[skill]
        correct = sum(status == 'correct' for _, status in group)
        total = len(group)
        score = round(100 * correct / total, 2)
        status = 'strong' if 100 * correct >= 75 * total else 'review'
        target = [row for row, state in group if state != 'correct'] or [row for row, _ in group]
        topics = list(dict.fromkeys(
            row['topic'] if version in {'scenarios-v5', 'scenarios-v6'} and isinstance(row.get('topic'), str) and row['topic'].strip()
            else _TOPICS.get(row.get('family'), 'Разбор условий и эталонов сохранённой формы')
            for row in target))
        action = 'Закрепите' if status == 'strong' else 'Повторите'
        recommendation = (f'{action} темы: {"; ".join(topics)}. '
                          f'Разберите условия и решите несколько примеров с другими данными. '
                          f'Откройте раздел «Практика» и выберите подходящий доступный набор. '
                          f'Практика не меняет глобальный грейд.')
        skills.append({'skill': skill, 'correct': correct, 'total': total,
                       'score': score, 'status': status, 'topics': topics,
                       'recommendation': recommendation})
    threshold = 70 if grade == 'junior' else 80
    return {'threshold': threshold, 'correct': sum(row['status'] == 'correct' for row in rows),
            'total': len(rows), 'needed_correct': (len(rows) * threshold + 99) // 100,
            'skills': skills, 'questions': rows}
