"""JavaScript-семейства: результат считается Python-зеркалом правил языка (проверено автором)."""
import json

from .core import make_brief, multiple, numeric, open_task, pick_distinct, plural, single
from .fam_py import assemble, fence


def arr(items):
    return '[ ' + ', '.join(map(str, items)) + ' ]' if items else '[]'


def js_bubbling(rng, grade):
    depth = rng.randint(3, 4)
    names = ['div#root', 'section#panel', 'button#go', 'span#label'][:depth] if depth == 4 else ['div#root', 'button#go', 'span#label']
    ids = [n.split('#')[1] for n in names]
    # какой элемент нажат: самый глубокий
    stop_at = None
    capture_at = None
    if grade == 'middle':
        stop_at = rng.choice(range(1, depth - 1)) if depth > 2 else None
        if rng.random() < 0.5:
            capture_at = 0
    lines = []
    for i, name in enumerate(names):
        ident = ids[i]
        opts = ', true' if capture_at == i else ''
        body = f"log('{ident}')"
        if stop_at == i:
            body += '; e.stopPropagation()'
        lines.append(f"document.getElementById('{ident}').addEventListener('click', e => {{ {body}; }}{opts});")
    # порядок: capture-слушатели сверху вниз, затем bubble снизу вверх до stop
    fired = []
    if capture_at is not None:
        fired.append(ids[capture_at])
    for i in range(depth - 1, -1, -1):
        if capture_at == i:
            continue
        fired.append(ids[i])
        if stop_at == i:
            break
    structure = ' > '.join(names)
    code = '\n'.join(lines)
    intro = f'В DOM находится {structure}. Пользователь нажимает {names[-1]}. Функция log добавляет строку в журнал. Обработчики click:'
    out = ', '.join(fired)
    pool = []
    base = [ids[i] for i in range(depth - 1, -1, -1)]
    pool += [', '.join(base), ', '.join(reversed(base)), ids[-1], ', '.join(base[:-1]), ', '.join(sorted(ids))]
    if stop_at is not None:
        pool += [', '.join(base[:max(1, depth - stop_at - 1)]), ', '.join(base)]
    if capture_at is not None:
        pool += [', '.join(base), ', '.join(ids)]
    truths = [f'в журнал попадёт {plural(len(fired), "запись", "записи", "записей")}', f'первой в журнале будет запись {fired[0]}',
              f'последней в журнале будет запись {fired[-1]}']
    falses = [f'в журнал попадёт {plural(len(fired) + 1, "запись", "записи", "записей")}', f'первой в журнале будет запись {fired[-1] if fired[-1] != fired[0] else ids[0]}'
              if len(fired) > 1 else 'первой в журнале будет несуществующая запись',
              'обработчик внешнего элемента сработает до обработчиков вложенных без capture']
    if capture_at is None:
        falses[2] = 'обработчики сработают сверху вниз, от внешнего элемента к нажатому'
    else:
        falses[2] = 'capture-обработчик внешнего элемента сработает последним'
    if stop_at is None and capture_at is None:
        truths[2] = f'событие дойдёт до {ids[0]}, потому что stopPropagation нигде не вызывается'
    num_q = 'Сколько записей окажется в журнале?'
    rub = (f'в журнале {plural(len(fired), "запись", "записи", "записей")}: {out}; событие всплывает от нажатого элемента к внешним'
           + ('; capture-обработчик срабатывает раньше' if capture_at is not None else '')
           + (f'; stopPropagation на {ids[stop_at]} останавливает дальнейшее всплытие' if stop_at is not None else ''))
    res = assemble(rng, lang='javascript', code=code, correct_out=out, wrong_outs=pool,
                   title='Всплытие события click', question='Какие записи и в каком порядке попадут в журнал?',
                   topic='всплытии события и порядке обработчиков', truths=truths, falses=falses, num_q=num_q, num_v=len(fired),
                   num_unit='записей', open_q='Какие записи попадут в журнал и в каком порядке? Объясните порядок.',
                   zero='порядок не назван либо считается, что срабатывает только нажатый элемент',
                   fifty=f'назван состав записей, но порядок или роль stopPropagation/capture не объяснены',
                   hundred=rub, skills=['javascript'], spec='frontend', scenario_intro=intro,
                   restr='Не добавляйте других обработчиков и программных кликов.')
    return res


def js_arrays(rng, grade):
    data = [rng.randint(1, 20) for _ in range(rng.randint(5, 7))]
    kind = rng.choice(['filter_map', 'reduce', 'sort_default', 'slice_splice', 'find'])
    if kind == 'filter_map':
        t, m = rng.randint(4, 12), rng.randint(2, 5)
        code = f'const data = {json.dumps(data)};\nconst result = data.filter(x => x > {t}).map(x => x * {m});\nconsole.log(result);'
        res = [x * m for x in data if x > t]
        if not res or len(res) == len(data):
            raise ValueError('вырожденно')
        out = arr(res)
        wrongs = [arr([x for x in data if x > t]), arr([x * m for x in data]),
                  arr([x * m for x in data if x * m > t]), arr([x for x in data if x <= t])]
        num_q, num_v, unit = 'Чему равна сумма элементов выведенного массива?', sum(res), ''
        truths = [f'длина result равна {len(res)}', f'сумма элементов result равна {sum(res)}', 'filter не изменяет исходный массив data']
        falses = [f'длина result равна {len(data)}', f'сумма элементов result равна {sum(x * m for x in data)}', 'filter изменяет исходный массив data']
        hundred = f'result = {out}; filter оставляет элементы больше {t} до умножения, map умножает каждый на {m}; data не меняется'
        title = 'Цепочка filter и map'
        open_q = 'Что выведет код и в каком порядке выполняются filter и map?'
        fifty = f'верно назван результат {out}, но не объяснён порядок filter и map'
    elif kind == 'reduce':
        init = rng.randint(0, 10)
        code = f'const data = {json.dumps(data)};\nconst total = data.reduce((acc, x) => acc + x, {init});\nconsole.log(total);'
        total = sum(data) + init
        out = str(total)
        wrongs = [str(sum(data)), str(total - init + 1), str(sum(data[1:]) + init), str(total + data[0]), str(init)]
        num_q, num_v, unit = 'Чему равно значение total?', total, ''
        truths = [f'начальное значение acc равно {init}', f'total равно {total}', 'reduce не изменяет исходный массив']
        falses = [f'total равно {sum(data) if init else sum(data) + 1}', f'начальное значение acc равно {data[0] if data[0] != init else init + 1}', 'reduce возвращает массив']
        hundred = f'выведено {total}; acc начинается с {init}, к нему прибавляются все {plural(len(data), "элемент", "элемента", "элементов")} массива'
        title = 'Сумма через reduce'
        open_q = 'Что выведет код и какую роль играет второй аргумент reduce?'
        fifty = f'верно назван результат {total}, но не объяснён начальный аккумулятор'
    elif kind == 'sort_default':
        data = [rng.choice([1, 2, 5, 9, 10, 11, 20, 100, 25, 3]) for _ in range(5)]
        data = list(dict.fromkeys(data))
        if len(data) < 4:
            raise ValueError('мало')
        code = f'const data = {json.dumps(data)};\ndata.sort();\nconsole.log(data);'
        res = sorted(data, key=str)
        out = arr(res)
        if res == sorted(data):
            raise ValueError('сортировка совпала')
        wrongs = [arr(sorted(data)), arr(sorted(data, reverse=True)), arr(data)]
        num_q, num_v, unit = 'Какое число окажется первым в выведенном массиве?', res[0], ''
        truths = ['sort без функции сравнения сравнивает элементы как строки', 'sort изменяет исходный массив', f'первым в выведенном массиве окажется {res[0]}']
        falses = ['sort без функции сравнения сортирует числа по значению', 'sort возвращает новый массив и не меняет data', f'первым в выведенном массиве окажется {min(data) if min(data) != res[0] else max(data)}']
        hundred = f'выведено {out}; по умолчанию sort сравнивает строковые представления, поэтому, например, 10 идёт раньше 9; для чисел нужна функция сравнения (a, b) => a - b'
        title = 'Сортировка чисел по умолчанию'
        open_q = 'Что выведет код и как получить числовую сортировку?'
        fifty = f'верно назван результат {out}, но нет причины или исправления'
    elif kind == 'slice_splice':
        a, b = sorted(rng.sample(range(1, len(data)), 2))
        sliced = data[a:b]
        removed = data[a:b]
        arr2 = list(data)
        del arr2[a:b]
        code = (f'const data = {json.dumps(data)};\nconst part = data.slice({a}, {b});\n'
                f'const removed = data.splice({a}, {b - a});\nconsole.log(part.length, removed.length, data.length);')
        out = f'{len(sliced)} {len(removed)} {len(arr2)}'
        wrongs = [f'{len(sliced)} {len(removed)} {len(data)}', f'{len(sliced) + 1} {len(removed)} {len(arr2)}', f'{len(arr2)} {len(removed)} {len(sliced)}', f'{len(sliced)} {len(data)} {len(arr2)}']
        num_q, num_v, unit = 'Чему равна data.length в конце?', len(arr2), ''
        truths = ['slice не изменяет исходный массив', 'splice изменяет исходный массив', f'в конце data.length равна {len(arr2)}']
        falses = ['slice удаляет элементы из исходного массива', 'splice не изменяет исходный массив', f'в конце data.length равна {len(data)}']
        hundred = f'выведено {out}; slice копирует часть без изменения data, splice удаляет {plural(len(removed), "элемент", "элемента", "элементов")} из data, длина становится {len(arr2)}'
        title = 'slice и splice'
        open_q = 'Что выведет код и чем slice отличается от splice?'
        fifty = f'верно назван вывод {out}, но не объяснено, какой метод изменяет массив'
    else:
        t = rng.randint(5, 15)
        code = f'const data = {json.dumps(data)};\nconsole.log(data.find(x => x > {t}), data.findIndex(x => x > {t}));'
        f = next((x for x in data if x > t), None)
        idx = next((i for i, x in enumerate(data) if x > t), -1)
        if f is None:
            raise ValueError('нет')
        out = f'{f} {idx}'
        wrongs = [f'{idx} {f}', f'{f} {idx + 1}', f'{[x for x in data if x > t][-1]} {len(data) - 1}', f'undefined -1', f'{f} -1']
        num_q, num_v, unit = 'Какой индекс выведет findIndex?', idx, ''
        truths = ['find возвращает первый подходящий элемент', 'findIndex возвращает индекс первого подходящего элемента', f'findIndex вернёт {idx}']
        falses = ['find возвращает массив всех подходящих элементов', 'findIndex возвращает последний подходящий индекс', f'findIndex вернёт {idx + 1}']
        hundred = f'выведено {out}; find и findIndex возвращают первый подходящий элемент и его индекс, а не все совпадения'
        title = 'find и findIndex'
        open_q = 'Что выведет код и что вернули бы методы, если подходящего элемента нет?'
        fifty = f'верно назван вывод {out}, но не описан случай без совпадений'
        hundred += '; без совпадений find вернёт undefined, findIndex — -1'
    return assemble(rng, lang='javascript', code=code, correct_out=out, wrong_outs=wrongs, title=title,
                    question='Что выведет код?', topic='методах массивов JavaScript', truths=truths, falses=falses,
                    num_q=num_q, num_v=num_v, num_unit=unit, open_q=open_q,
                    zero='вывод не назван либо поведение метода описано неверно', fifty=fifty, hundred=hundred,
                    skills=['javascript'], spec=rng.choice(['frontend', 'backend']),
                    scenario_intro='Дан фрагмент кода на JavaScript.')


EQ = [  # (выражение, результат как текст, булево если результат true/false)
    ("0 == '0'", 'true'), ("null == undefined", 'true'), ("null === undefined", 'false'), ("NaN == NaN", 'false'),
    ("'' == 0", 'true'), ("[] == false", 'true'), ("'5' + 3", '53'), ("'5' - 3", '2'), ("typeof null", 'object'),
    ("0.1 + 0.2 === 0.3", 'false'), ("'b' + 'a' + +'a' + 'a'", 'baNaNa'), ("[] + []", ''), ("typeof NaN", 'number'),
    ("1 < 2 < 3", 'true'), ("3 > 2 > 1", 'false'), ("'10' > '9'", 'false'), ("10 > 9", 'true'), ("null == 0", 'false'),
    ("undefined == 0", 'false'), ("!!'0'", 'true'), ("!!''", 'false'), ("Boolean([])", 'true'), ("[] + {}", '[object Object]'),
    ("2 + '2'", '22'), ("'2' * '3'", '6'), ("typeof []", 'object'), ("typeof undefined", 'undefined'), ("1 + true", '2'),
]


def js_equality(rng, grade):
    pool = [x for x in EQ if x[1] in {'true', 'false'}]
    n = rng.randint(4, 5)
    picks = rng.sample(pool, n)
    code = '\n'.join(f'console.log({e});' for e, _ in picks)
    out = '\n'.join(v for _, v in picks)
    trues = sum(v == 'true' for _, v in picks)
    if trues in (0, n):
        raise ValueError('однотонно')
    flipped = ['false' if v == 'true' else 'true' for _, v in picks]
    wrongs = ['\n'.join(flipped), '\n'.join(v if i != 0 else flipped[0] for i, (_, v) in enumerate(picks)),
              '\n'.join(v if i != n - 1 else flipped[-1] for i, (_, v) in enumerate(picks)),
              '\n'.join(v if i != 1 else flipped[1] for i, (_, v) in enumerate(picks))]
    truths = [f'выражение {picks[i][0]} даёт {picks[i][1]}' for i in range(n) if True]
    t_ok = [f'выражение {e} даёт {v}' for e, v in picks]
    t_bad = [f'выражение {e} даёт {"false" if v == "true" else "true"}' for e, v in picks]
    return assemble(rng, lang='javascript', code=code, correct_out=out, wrong_outs=wrongs, title='Сравнения и приведение типов',
                    question=f'Что выведет код ({n} строк)?', topic='сравнениях и приведении типов в JavaScript',
                    truths=t_ok, falses=t_bad, num_q='Сколько строк будет выведено со значением true?', num_v=trues, num_unit='строк',
                    open_q='Что выведет код? Объясните результат для каждого выражения.',
                    zero='вывод не назван либо правила приведения типов не упомянуты',
                    fifty='верно названа большая часть значений, но объяснено менее половины выражений',
                    hundred=f'вывод: {", ".join(v for _, v in picks)}; для каждого выражения объяснено правило: нестрогое сравнение приводит типы, строгое нет, NaN не равно себе, строки сравниваются посимвольно',
                    skills=['javascript'], spec=rng.choice(['frontend', 'qa']), scenario_intro='Дан фрагмент кода на JavaScript.')


def js_loop_closure(rng, grade):
    n = rng.randint(3, 4)
    use_var = rng.choice([True, False])
    decl = 'var' if use_var else 'let'
    code = f'for ({decl} i = 0; i < {n}; i++) {{\n  setTimeout(() => console.log(i), 0);\n}}'
    res = [n] * n if use_var else list(range(n))
    out = ' '.join(map(str, res))
    other = [n] * n if not use_var else list(range(n))
    wrongs = [' '.join(map(str, other)), ' '.join(map(str, range(1, n + 1))), ' '.join(map(str, reversed(range(n)))), str(n)]
    truths = [f'вывод содержит {plural(n, "число", "числа", "чисел")}', 'колбэки setTimeout выполняются после завершения цикла',
              ('все колбэки видят одну общую переменную i' if use_var else 'на каждой итерации создаётся своя привязка i')]
    falses = [f'вывод содержит {plural(n + 1, "число", "числа", "чисел")}', 'колбэки setTimeout выполняются во время итераций цикла',
              ('на каждой итерации создаётся своя привязка i' if use_var else 'все колбэки видят одну общую переменную i')]
    return assemble(rng, lang='javascript', code=code, correct_out=out, wrong_outs=wrongs, title=f'Цикл с {decl} и setTimeout',
                    question='Что выведет код?', topic='замыканиях в цикле и области видимости var/let',
                    truths=truths, falses=falses, num_q='Чему равно первое выведенное число?', num_v=res[0], num_unit='',
                    open_q='Что выведет код и почему результат зависит от var/let?',
                    zero='вывод не назван либо причина названа случайностью',
                    fifty=f'верно назван вывод {out}, но нет объяснения области видимости',
                    hundred=f'вывод {out}; колбэки выполняются после цикла; {"var даёт одну переменную на функцию, поэтому все видят последнее значение " + str(n) if use_var else "let создаёт новую привязку на каждой итерации, поэтому колбэки видят свои значения"}',
                    skills=['javascript'], spec='frontend', scenario_intro='Дан фрагмент кода на JavaScript.')


def js_event_loop(rng, grade):
    labels = rng.sample(['A', 'B', 'C', 'D', 'E', 'F'], rng.randint(4, 5))
    kinds = ['sync', 'timeout', 'promise', 'sync', 'promise'][:len(labels)]
    rng.shuffle(kinds)
    if 'timeout' not in kinds:
        kinds[0] = 'timeout'
    if 'promise' not in kinds:
        kinds[-1] = 'promise'
    if 'sync' not in kinds:
        kinds[1] = 'sync'
    lines, sync, micro, macro = [], [], [], []
    for order, (label, kind) in enumerate(zip(labels, kinds)):
        if kind == 'sync':
            lines.append(f"console.log('{label}');")
            sync.append(label)
        elif kind == 'promise':
            lines.append(f"Promise.resolve().then(() => console.log('{label}'));")
            micro.append(label)
        else:
            delay = rng.choice([0, 0, 10]) if grade == 'middle' else 0
            lines.append(f"setTimeout(() => console.log('{label}'), {delay});")
            macro.append((delay, order, label))
    macro_sorted = [l for _, _, l in sorted(macro)]
    res = sync + micro + macro_sorted
    code = '\n'.join(lines)
    out = ' '.join(res)
    wrongs = [' '.join(labels), ' '.join(sync + macro_sorted + micro), ' '.join(micro + sync + macro_sorted),
              ' '.join(sync + [l for _, _, l in sorted(macro, key=lambda m: m[1])] + micro), ' '.join(reversed(res))]
    truths = ['синхронные вызовы console.log выполняются первыми', 'колбэки Promise.then выполняются раньше колбэков setTimeout',
              f'первой будет выведена буква {res[0]}']
    falses = ['колбэки setTimeout с задержкой 0 выполняются раньше Promise.then', 'порядок вывода совпадает с порядком строк кода',
              f'последней будет выведена буква {res[0] if res[0] != res[-1] else labels[0]}']
    return assemble(rng, lang='javascript', code=code, correct_out=out, wrong_outs=wrongs, title='Порядок вывода: Promise и setTimeout',
                    question='В каком порядке будут выведены буквы?', topic='очереди микрозадач и таймеров в JavaScript',
                    truths=truths, falses=falses, num_q='Какой по счёту будет выведена последняя буква строки кода (номер в выводе)?' if False else 'Сколько букв будет выведено до первого колбэка setTimeout?',
                    num_v=len(sync) + len(micro), num_unit='букв',
                    open_q='В каком порядке будут выведены буквы и почему?',
                    zero='порядок не назван либо принят порядок строк кода',
                    fifty=f'верно названы синхронные вызовы, но неверно упорядочены Promise и setTimeout',
                    hundred=f'порядок: {out}; сначала синхронный код, затем микрозадачи (Promise.then), затем макрозадачи (setTimeout) по задержке и порядку добавления',
                    skills=['javascript'], spec='frontend', scenario_intro='Дан фрагмент кода на JavaScript.')


FAMILIES = [js_bubbling, js_arrays, js_equality, js_loop_closure, js_event_loop]
