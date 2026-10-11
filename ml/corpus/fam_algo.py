"""Алгоритмические и дополнительные вычисляемые семейства (тематика соревнований ФСП: алгоритмы, продукт, ИБ).

Истина — выполнение кода при сборке. Ни одно семейство не совпадает с закрытым набором v3
(split/LIMIT-OFFSET/??/If-Match/таблица решений/alt).
"""
import math
import sqlite3
from collections import deque

from .core import make_brief, multiple, numeric, open_task, pick_distinct, plural, single
from .fam_py import assemble, fence
from .runcode import py_out


def algo_binary_search(rng, grade):
    n = rng.randint(8, 40) if grade == 'junior' else rng.randint(40, 500)
    data = sorted(rng.sample(range(1, n * 4), n))
    target = rng.choice(data + [data[0] - 1 if data[0] > 1 else data[-1] + 1])
    code = ('def find(items, target):\n    lo, hi = 0, len(items) - 1\n    steps = 0\n    while lo <= hi:\n        steps += 1\n'
            '        mid = (lo + hi) // 2\n        if items[mid] == target:\n            return steps\n        if items[mid] < target:\n            lo = mid + 1\n'
            '        else:\n            hi = mid - 1\n    return -steps\n\n'
            f'items = list(range(1, {n + 1}))\nprint(find(items, {rng.randint(1, n)}))')
    t = int(code.rsplit('find(items, ', 1)[1].rstrip(')'))
    steps = int(py_out(code))
    worst = math.ceil(math.log2(n + 1))
    wrongs = [str(steps + 1), str(-steps), str(t), str(n // 2), str(max(1, steps - 1))]
    truths = [f'массив отсортирован, поэтому бинарный поиск допустим', f'в худшем случае нужно не больше {worst} сравнений для {n} элементов',
              'каждая итерация уменьшает диапазон поиска примерно вдвое']
    falses = [f'в худшем случае нужно {n} сравнений', 'бинарный поиск работает и на неотсортированном массиве', 'сложность бинарного поиска равна O(n)']
    return assemble(rng, lang='python', code=code, correct_out=str(steps), wrong_outs=wrongs, title='Бинарный поиск: число шагов',
                    question='Что выведет программа?', topic='числе шагов бинарного поиска', truths=truths, falses=falses,
                    num_q=f'Чему равно максимальное число итераций цикла при поиске в массиве из {n} элементов?', num_v=worst, num_unit='итераций',
                    open_q='Что выведет программа, как работает бинарный поиск и какова его сложность?',
                    zero='результат не назван либо бинарный поиск описан как перебор', fifty=f'верно назван результат {steps}, но нет оценки сложности',
                    hundred=f'результат {steps}; диапазон lo..hi сужается вдвое по сравнению с серединой; сложность O(log n), нужен отсортированный массив; максимум {worst} итераций',
                    skills=['python'], spec='backend', scenario_intro='Дана функция поиска на Python.')


def algo_nested_loops(rng, grade):
    n, m = rng.randint(3, 7), rng.randint(3, 8)
    variant = rng.choice(['full', 'triangle', 'step'])
    if variant == 'full':
        loop = f'for i in range({n}):\n    for j in range({m}):\n        count += 1'
        calc = n * m
        big_o = 'O(n·m)'
    elif variant == 'triangle':
        loop = f'for i in range({n}):\n    for j in range(i):\n        count += 1'
        calc = n * (n - 1) // 2
        big_o = 'O(n²)'
    else:
        step = rng.choice([2, 3])
        loop = f'for i in range(0, {n * 4}, {step}):\n    for j in range({m}):\n        count += 1'
        calc = len(range(0, n * 4, step)) * m
        big_o = 'O(n·m)'
    code = f'count = 0\n{loop}\nprint(count)'
    assert int(py_out(code)) == calc
    wrongs = [str(calc + m), str(calc - 1), str(n * m + 1 if variant != 'full' else n + m), str(calc * 2), str(n * n)]
    truths = [f'счётчик count в конце равен {calc}', 'внутренний цикл выполняется заново на каждой итерации внешнего', f'порядок роста числа операций: {big_o}']
    falses = [f'счётчик count в конце равен {calc + 1}', 'внутренний цикл выполняется один раз за всю программу', 'число операций не зависит от границ циклов']
    return assemble(rng, lang='python', code=code, correct_out=str(calc), wrong_outs=wrongs, title='Число операций во вложенных циклах',
                    question='Что выведет программа?', topic='подсчёте операций во вложенных циклах', truths=truths, falses=falses,
                    num_q='Сколько раз выполнится строка count += 1?', num_v=calc, num_unit='раз',
                    open_q='Что выведет программа и как оценить сложность вложенных циклов?',
                    zero='результат не назван либо вложенные циклы просуммированы вместо перемножения',
                    fifty=f'верно назван результат {calc}, но нет оценки сложности',
                    hundred=f'результат {calc}; внутренний цикл выполняется на каждой итерации внешнего, число операций перемножается; сложность {big_o}',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def algo_graph_bfs(rng, grade):
    n = rng.randint(5, 7)
    nodes = list(range(1, n + 1))
    edges = set()
    while len(edges) < n + 1:
        a, b = rng.sample(nodes, 2)
        edges.add((min(a, b), max(a, b)))
    edges = sorted(edges)
    adj = {v: [] for v in nodes}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    src = 1
    dist = {src: 0}
    q = deque([src])
    while q:
        v = q.popleft()
        for w in sorted(adj[v]):
            if w not in dist:
                dist[w] = dist[v] + 1
                q.append(w)
    target = rng.choice([v for v in nodes if v in dist and v != src] or [None])
    if target is None:
        raise ValueError('нет цели')
    reachable = len(dist)
    far = max(dist.values())
    text = f'Неориентированный граф с вершинами 1–{n} и рёбрами: ' + ', '.join(f'{a}–{b}' for a, b in edges) + '. '
    scenario = text.strip()
    topic = 'поиске в ширину и кратчайших путях в графе'
    out = {}
    out['numeric'] = (numeric('Кратчайший путь в графе', text + f'Чему равно минимальное число рёбер на пути от вершины 1 до вершины {target}?', dist[target], 'рёбер', ['python']),
                      make_brief(rng, 'numeric', scenario, topic))
    right = str(dist[target])
    wrongs = pick_distinct(rng, [right], [str(dist[target] + 1), str(max(0, dist[target] - 1)), str(reachable), str(far + 2), str(len(edges))], 3)
    out['single_choice'] = (single(rng, 'Кратчайший путь поиском в ширину', text + f'Каково минимальное число рёбер от вершины 1 до вершины {target}?', right, wrongs, ['python']),
                            make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'из вершины 1 достижимо {plural(reachable, "вершина", "вершины", "вершин")} (считая саму вершину 1)', f'самая дальняя достижимая вершина находится на расстоянии {far}',
          f'расстояние до вершины {target} равно {dist[target]}']
    bad = [f'из вершины 1 достижимо {plural(reachable + 1, "вершина", "вершины", "вершин")}', f'самая дальняя достижимая вершина находится на расстоянии {far + 1}', f'расстояние до вершины {target} равно {dist[target] + 1}']
    out['multiple_choice'] = (multiple(rng, 'Свойства графа и обхода', text + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['python']),
                              make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Поиск в ширину', text + f'Опишите, как найти кратчайший путь от вершины 1 до вершины {target} поиском в ширину и каков результат.',
                                      'алгоритм не описан либо предложен поиск в глубину без обоснования',
                                      f'назван результат {dist[target]}, но не описана очередь и уровни',
                                      f'результат {dist[target]}; используется очередь, вершины обходятся по уровням, расстояние до соседа на единицу больше; сложность O(V+E)',
                                      ['python']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['python'], 'tasks': out}


def algo_stack_queue(rng, grade):
    ops = []
    stack, queue = [], deque()
    items = rng.sample(range(1, 20), 5)
    code_lines = ['stack = []', 'queue = []']
    k = 0
    for _ in range(rng.randint(5, 7)):
        if k < len(items) and (rng.random() < 0.65 or not stack):
            v = items[k]; k += 1
            code_lines.append(f'stack.append({v}); queue.append({v})')
        else:
            code_lines.append('a = stack.pop(); b = queue.pop(0); out.append((a, b))' if False else 'out.append((stack.pop(), queue.pop(0)))')
    code = 'out = []\n' + '\n'.join(code_lines) + '\nprint(out)'
    try:
        out = py_out(code)
    except IndexError:
        raise ValueError('pop из пустого')
    if 'out.append' not in code:
        raise ValueError('нет pop')
    res = eval(out)
    swapped = str([(b, a) for a, b in res])
    wrongs = [swapped, str([(a, a) for a, _ in res]), str([(b, b) for _, b in res]), str(res[::-1])]
    truths = ['stack.pop() извлекает последний добавленный элемент (LIFO)', 'queue.pop(0) извлекает первый добавленный элемент (FIFO)', f'выведено {plural(len(res), "пара", "пары", "пар")}']
    falses = ['stack.pop() извлекает первый добавленный элемент', 'queue.pop(0) извлекает последний добавленный элемент', f'выведено {plural(len(res) + 1, "пара", "пары", "пар")}']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs, title='Стек и очередь на списках',
                    question='Что выведет программа?', topic='порядке извлечения из стека и очереди', truths=truths, falses=falses,
                    num_q='Чему равна сумма всех чисел в первом элементе каждой выведенной пары?', num_v=sum(a for a, _ in res), num_unit='',
                    open_q='Что выведет программа и чем стек отличается от очереди?', zero='вывод не назван либо LIFO и FIFO перепутаны',
                    fifty=f'верно назван вывод {out}, но нет определения LIFO и FIFO',
                    hundred=f'вывод {out}; стек извлекает последний добавленный элемент (LIFO), очередь — первый (FIFO); pop(0) у списка занимает O(n), для очереди лучше deque',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def algo_sort_stability(rng, grade):
    names = rng.sample(['Анна', 'Борис', 'Вера', 'Глеб', 'Дарья', 'Егор'], 5)
    scores = [rng.choice([70, 80, 90]) for _ in names]
    rows = list(zip(names, scores))
    code = f'rows = {rows}\nprint([n for n, s in sorted(rows, key=lambda r: r[1], reverse=True)])'
    out = py_out(code)
    unstable = str([n for n, s in sorted(rows, key=lambda r: (-r[1], r[0]))])
    rev = str([n for n, s in reversed(sorted(rows, key=lambda r: r[1]))])
    wrongs = [unstable, rev, str([n for n, s in sorted(rows, key=lambda r: r[1])]), str(sorted(names))]
    if unstable == out:
        wrongs = wrongs[1:]
    truths = ['sorted() в Python устойчива: равные по ключу элементы сохраняют исходный порядок', 'reverse=True сохраняет относительный порядок равных элементов', 'sorted() возвращает новый список и не меняет rows']
    falses = ['при равных ключах порядок элементов случайный', 'sorted() изменяет исходный список rows', 'reverse=True переворачивает порядок равных элементов']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs, title='Устойчивая сортировка',
                    question='Что выведет программа?', topic='устойчивости сортировки в Python', truths=truths, falses=falses,
                    num_q='Сколько человек имеют максимальный балл?', num_v=sum(1 for _, s in rows if s == max(scores)), num_unit='человек',
                    open_q='Что выведет программа и что значит «устойчивая сортировка»?', zero='вывод не назван либо порядок равных элементов объявлен случайным',
                    fifty=f'верно назван вывод {out}, но нет определения устойчивости',
                    hundred=f'вывод {out}; устойчивая сортировка сохраняет исходный порядок элементов с равными ключами, sorted в Python устойчива, в том числе с reverse=True',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def algo_recursion(rng, grade):
    n = rng.randint(4, 9)
    kind = rng.choice(['fib', 'fact'])
    if kind == 'fib':
        code = ('calls = 0\n\ndef fib(n):\n    global calls\n    calls += 1\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\n\n'
                f'print(fib({n}), calls)')
        title, topic = 'Рекурсия Фибоначчи и число вызовов', 'числе вызовов рекурсивной функции'
        hundred_extra = 'число вызовов растёт экспоненциально, повторные вычисления устраняет мемоизация'
    else:
        code = ('calls = 0\n\ndef fact(n):\n    global calls\n    calls += 1\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\n'
                f'print(fact({n}), calls)')
        title, topic = 'Рекурсия факториала и число вызовов', 'числе вызовов рекурсивной функции'
        hundred_extra = 'число вызовов растёт линейно, глубина рекурсии равна n'
    out = py_out(code)
    value, calls = map(int, out.split())
    wrongs = [f'{value} {calls + 1}', f'{value} {calls - 1}', f'{value + 1} {calls}', f'{calls} {value}', f'{value} {n}']
    truths = [f'значение функции равно {value}', f'всего выполнено {plural(calls, "вызов", "вызова", "вызовов")}', 'у рекурсии должно быть условие остановки']
    falses = [f'значение функции равно {value + 1}', f'всего выполнено {plural(calls + 1, "вызов", "вызова", "вызовов")}', 'условие остановки рекурсии необязательно']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs, title=title,
                    question='Что выведет программа (значение и число вызовов через пробел)?', topic=topic, truths=truths, falses=falses,
                    num_q='Сколько раз была вызвана функция?', num_v=calls, num_unit='вызовов',
                    open_q='Что выведет программа и как растёт число вызовов?', zero='вывод не назван либо рекурсия объяснена как цикл',
                    fifty=f'верно назван вывод {out}, но нет оценки роста числа вызовов',
                    hundred=f'вывод {out}; {hundred_extra}; базовый случай останавливает рекурсию', skills=['python'], spec='backend',
                    scenario_intro='Дан фрагмент кода на Python.')


def sql_window_rank(rng, grade):
    names = rng.sample(['Анна', 'Борис', 'Вера', 'Глеб', 'Дарья', 'Егор'], rng.randint(4, 5))
    pts = [rng.choice([10, 20, 20, 30, 40]) for _ in names]
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE players(name TEXT, points INTEGER)')
    for n, p in zip(names, pts):
        con.execute('INSERT INTO players VALUES (?, ?)', (n, p))
    rank = dict(con.execute('SELECT name, RANK() OVER (ORDER BY points DESC) FROM players').fetchall())
    dense = dict(con.execute('SELECT name, DENSE_RANK() OVER (ORDER BY points DESC) FROM players').fetchall())
    who = rng.choice(names)
    if len(set(pts)) == len(pts) or len(set(pts)) == 1:
        raise ValueError('нет ничьих')
    data = 'Таблица players(name, points): ' + '; '.join(f'({n}, {p})' for n, p in zip(names, pts)) + '. '
    scenario = 'В SQLite ' + data.strip()
    topic = 'оконных функциях RANK и DENSE_RANK'
    out = {}
    out['numeric'] = (numeric('RANK при ничьих', data + f'Какое значение вернёт RANK() OVER (ORDER BY points DESC) для игрока {who}?', rank[who], '', ['sql']), make_brief(rng, 'numeric', scenario, topic))
    right = f'RANK = {rank[who]}, DENSE_RANK = {dense[who]}'
    alts = [f'RANK = {dense[who]}, DENSE_RANK = {rank[who]}', f'RANK = {rank[who] + 1}, DENSE_RANK = {dense[who]}', f'RANK = {rank[who]}, DENSE_RANK = {dense[who] + 1}', f'RANK = {dense[who]}, DENSE_RANK = {dense[who]}']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'RANK и DENSE_RANK', data + f'Какие значения вернут RANK() и DENSE_RANK() с ORDER BY points DESC для игрока {who}?', right, wrongs, ['sql']), make_brief(rng, 'single_choice', scenario, topic))
    ok = ['RANK оставляет пропуски в нумерации после ничьих', 'DENSE_RANK не оставляет пропусков после ничьих', f'максимальный DENSE_RANK равен {max(dense.values())}']
    bad = ['RANK не оставляет пропусков после ничьих', 'DENSE_RANK оставляет пропуски в нумерации', f'максимальный DENSE_RANK равен {max(dense.values()) + 1}']
    out['multiple_choice'] = (multiple(rng, 'Оконные функции ранжирования', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['sql']), make_brief(rng, 'multiple_choice', scenario, topic))
    listing = '; '.join(f'{n}: RANK {rank[n]}, DENSE_RANK {dense[n]}' for n in names)
    out['open_response'] = (open_task('Ранжирование оконными функциями', data + 'Опишите значения RANK и DENSE_RANK для каждого игрока и объясните разницу.',
                                      'значения не названы либо RANK и DENSE_RANK считаются одинаковыми',
                                      'верно названы значения одной из функций, но нет сравнения',
                                      f'{listing}; RANK оставляет пропуски после ничьих, DENSE_RANK нумерует подряд', ['sql']), make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def sql_count_distinct(rng, grade):
    users = rng.sample(['u1', 'u2', 'u3', 'u4'], 3)
    rows = [(rng.choice(users), rng.choice(['login', 'view', 'buy'])) for _ in range(rng.randint(6, 9))]
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE events(user_id TEXT, action TEXT)')
    con.executemany('INSERT INTO events VALUES (?, ?)', rows)
    total = con.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    du = con.execute('SELECT COUNT(DISTINCT user_id) FROM events').fetchone()[0]
    da = con.execute('SELECT COUNT(DISTINCT action) FROM events').fetchone()[0]
    dpair = con.execute('SELECT COUNT(*) FROM (SELECT DISTINCT user_id, action FROM events)').fetchone()[0]
    if len({total, du, dpair}) < 3 or total <= dpair:
        raise ValueError('совпадения')
    data = 'Таблица events(user_id, action): ' + '; '.join(f'({u}, {a})' for u, a in rows) + '. '
    scenario = 'В SQLite ' + data.strip()
    topic = 'COUNT(DISTINCT) и подсчёте уникальных значений'
    out = {}
    out['numeric'] = (numeric('Уникальные пользователи', data + 'Чему равно COUNT(DISTINCT user_id)?', du, '', ['sql']), make_brief(rng, 'numeric', scenario, topic))
    right = f'{total}, {du}, {da}'
    alts = [f'{du}, {total}, {da}', f'{total}, {da}, {du}', f'{total}, {du}, {dpair}', f'{dpair}, {du}, {da}', f'{du}, {da}, {total}']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'COUNT и COUNT DISTINCT', data + 'Какие значения вернут COUNT(*), COUNT(DISTINCT user_id) и COUNT(DISTINCT action)?', right, wrongs, ['sql']), make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'COUNT(*) равно {total}', f'COUNT(DISTINCT user_id) равно {du}', f'число различных пар (user_id, action) равно {dpair}']
    bad = [f'COUNT(*) равно {du}', f'COUNT(DISTINCT action) равно {total}', f'число различных пар (user_id, action) равно {total + 1}']
    out['multiple_choice'] = (multiple(rng, 'Подсчёт уникальных значений', data + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['sql']), make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('COUNT(DISTINCT)', data + 'Вычислите COUNT(*), COUNT(DISTINCT user_id), COUNT(DISTINCT action) и объясните разницу.',
                                      'значения не вычислены либо DISTINCT считается фильтром по первым строкам',
                                      f'верно вычислено {total} и {du}, но нет третьего значения или объяснения',
                                      f'COUNT(*)={total}, пользователей {du}, действий {da}; DISTINCT считает различные значения, COUNT(*) считает все строки', ['sql']),
                            make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def js_destructure_spread(rng, grade):
    a, b, c = rng.sample(range(1, 30), 3)
    d = rng.randint(1, 9)
    code = (f'const base = {{ x: {a}, y: {b} }};\nconst copy = {{ ...base, y: {c}, z: {d} }};\nconst {{ x, ...rest }} = copy;\n'
            'console.log(base.y, copy.y, Object.keys(rest).length, x);')
    out = f'{b} {c} 2 {a}'
    wrongs = [f'{c} {c} 2 {a}', f'{b} {c} 3 {a}', f'{b} {b} 2 {a}', f'{b} {c} 2 {c}']
    truths = ['spread создаёт поверхностную копию свойств объекта', 'свойство после spread перезаписывает скопированное с тем же именем', 'исходный объект base не изменяется']
    falses = ['spread изменяет исходный объект base', 'свойство, указанное после spread, не перезаписывает скопированное', 'rest содержит все свойства объекта copy, включая x']
    return assemble(rng, lang='javascript', code=code, correct_out=out, wrong_outs=wrongs, title='Spread и деструктуризация объекта',
                    question='Что выведет код?', topic='spread и деструктуризации объектов в JavaScript', truths=truths, falses=falses,
                    num_q='Чему равно Object.keys(rest).length?', num_v=2, num_unit='',
                    open_q='Что выведет код и как работают spread и rest при работе с объектами?', zero='вывод не назван либо spread считается ссылкой на тот же объект',
                    fifty=f'верно назван вывод {out}, но нет объяснения перезаписи свойств',
                    hundred=f'вывод {out}; spread копирует свойства поверхностно, более поздние свойства перезаписывают; rest собирает остальные свойства без x, base не меняется',
                    skills=['javascript'], spec='frontend', scenario_intro='Дан фрагмент кода на JavaScript.')


def css_media_query(rng, grade):
    w = rng.choice([320, 480, 600, 768, 900, 1024, 1280, 1440])
    p, q = sorted(rng.sample([480, 600, 768, 1024], 2))
    rules = [('базовое правило', None, 'column'), (f'@media (min-width: {p}px)', ('min', p), 'row'), (f'@media (min-width: {q}px)', ('min', q), 'grid')]
    applied = [r for r in rules if r[1] is None or w >= r[1][1]]
    final = applied[-1][2]
    css = ('Базовое правило: .layout { display: column-стек }\n' + f'@media (min-width: {p}px) {{ .layout {{ display: ряд }} }}\n' + f'@media (min-width: {q}px) {{ .layout {{ display: сетка }} }}')
    lay = {'column': 'колонка', 'row': 'ряд', 'grid': 'сетка'}
    text = f'Заданы правила для .layout (в порядке объявления): по умолчанию — колонка; при min-width {p}px — ряд; при min-width {q}px — сетка. Ширина окна {w}px. '
    scenario = text.strip()
    topic = 'медиазапросах min-width и каскаде'
    out = {}
    out['single_choice'] = (single(rng, 'Какой макет применится', text + 'Какой макет применится к .layout?', lay[final], [v for k, v in lay.items() if k != final], ['html']), make_brief(rng, 'single_choice', scenario, topic))
    out['numeric'] = (numeric('Число сработавших правил', text + 'Сколько правил (включая базовое) применимы при этой ширине окна?', len(applied), 'правил', ['html']), make_brief(rng, 'numeric', scenario, topic))
    ok = [f'базовое правило применимо при любой ширине', f'применимо правил: {len(applied)}', f'итоговый макет — {lay[final]}']
    bad = [f'базовое правило отключается любым медиазапросом без перекрытия', f'применимо правил: {len(applied) + 1}', f'итоговый макет — {lay[[k for k in lay if k != final][0]]}']
    out['multiple_choice'] = (multiple(rng, 'Медиазапросы и каскад', text + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['html']), make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Медиазапросы min-width', text + 'Определите итоговый макет и объясните порядок применения правил.',
                                      'макет не определён либо порядок правил проигнорирован',
                                      f'назван макет ({lay[final]}), но не объяснён каскад',
                                      f'итоговый макет — {lay[final]}; подходят правила: {len(applied)}; при равной специфичности побеждает последнее подходящее по порядку объявления; min-width срабатывает при ширине не меньше порога', ['html']),
                            make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'frontend', 'skills': ['html'], 'tasks': out}


def http_url_query(rng, grade):
    host = rng.choice(['api.example.test', 'shop.example.test', 'data.example.test'])
    path = rng.choice(['/v1/items', '/search', '/orders/list'])
    keys = rng.sample(['page', 'limit', 'sort', 'q', 'lang', 'tag'], rng.randint(3, 4))
    vals = {'page': str(rng.randint(1, 9)), 'limit': str(rng.choice([10, 20, 50])), 'sort': rng.choice(['asc', 'desc']), 'q': rng.choice(['sql', 'http']), 'lang': 'ru', 'tag': rng.choice(['a', 'b'])}
    repeat = rng.choice(keys)
    pairs = [(k, vals[k]) for k in keys] + [(repeat, vals[repeat] + 'x')]
    url = f'https://{host}{path}?' + '&'.join(f'{k}={v}' for k, v in pairs) + '#top'
    n_params = len(pairs)
    n_unique = len({k for k, _ in pairs})
    text = f'Дан адрес: {url}. '
    scenario = text.strip()
    topic = 'составных частях URL и строке запроса'
    out = {}
    out['numeric'] = (numeric('Параметры строки запроса', text + 'Сколько пар «имя=значение» содержит строка запроса?', n_params, 'пар', ['http']), make_brief(rng, 'numeric', scenario, topic))
    right = f'схема https, хост {host}, путь {path}'
    alts = [f'схема https, хост {host}{path}, путь /', f'схема http, хост {host}, путь {path}', f'схема https, хост {host}, путь {path}?{pairs[0][0]}={pairs[0][1]}', f'схема {host}, хост https, путь {path}']
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Части URL', text + 'Как правильно разобрать адрес на схему, хост и путь?', right, wrongs, ['http']), make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'имя {repeat} встречается в строке запроса дважды', 'фрагмент #top не отправляется серверу в HTTP-запросе', f'различных имён параметров {n_unique}']
    bad = [f'различных имён параметров {n_params}', 'фрагмент #top отправляется серверу в строке запроса', f'строка запроса содержит {n_params + 1} пар']
    out['multiple_choice'] = (multiple(rng, 'Строка запроса и фрагмент', text + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['http']), make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Разбор URL', text + 'Разберите адрес на части и объясните, как сервер увидит повторяющиеся параметры.',
                                      'части адреса не названы либо фрагмент считается частью запроса к серверу',
                                      'верно названы схема, хост и путь, но нет строки запроса или фрагмента',
                                      f'схема https; хост {host}; путь {path}; строка запроса из {n_params} пар; фрагмент #top остаётся в браузере; повтор имени {repeat} зависит от фреймворка (список или последнее значение)', ['http']),
                            make_brief(rng, 'open_response', scenario, topic))
    return {'spec': rng.choice(['backend', 'frontend']), 'skills': ['http'], 'tasks': out}


def qa_risk_priority(rng, grade):
    feats = rng.sample(['оплата', 'вход', 'поиск', 'профиль', 'уведомления', 'экспорт'], 4)
    risk = {f: (rng.randint(1, 5), rng.randint(1, 5)) for f in feats}
    score = {f: p * i for f, (p, i) in risk.items()}
    if len(set(score.values())) < 4:
        raise ValueError('ничьи')
    order = sorted(feats, key=lambda f: -score[f])
    text = 'Риск функции = вероятность отказа (1–5) × влияние отказа (1–5). Функции: ' + '; '.join(f'{f} (вероятность {p}, влияние {i})' for f, (p, i) in risk.items()) + '. '
    scenario = text.strip()
    topic = 'приоритизации тестирования по рискам'
    out = {}
    top = order[0]
    out['numeric'] = (numeric('Максимальный риск', text + 'Чему равен наибольший риск среди функций?', score[top], '', ['testing']), make_brief(rng, 'numeric', scenario, topic))
    right = ', '.join(order)
    alts = [', '.join(order[::-1]), ', '.join(sorted(feats, key=lambda f: -risk[f][0])), ', '.join(sorted(feats, key=lambda f: -risk[f][1])), ', '.join(feats)]
    wrongs = pick_distinct(rng, [right], alts, 3)
    out['single_choice'] = (single(rng, 'Порядок тестирования по риску', text + 'В каком порядке тестировать функции — от наибольшего риска к наименьшему?', right, wrongs, ['testing']), make_brief(rng, 'single_choice', scenario, topic))
    ok = [f'риск функции «{top}» равен {score[top]}', f'первой по риску идёт функция «{top}»', f'риск функции «{order[-1]}» равен {score[order[-1]]}']
    bad = [f'риск функции «{top}» равен {score[top] + 1}', f'первой по риску идёт функция «{order[-1]}»', f'риск функции «{order[-1]}» равен {score[order[-1]] + 2}']
    out['multiple_choice'] = (multiple(rng, 'Риск-ориентированное тестирование', text + 'Какие утверждения верны? Выберите все верные.', ok[:rng.randint(2, 3)], bad[:2], ['testing']), make_brief(rng, 'multiple_choice', scenario, topic))
    out['open_response'] = (open_task('Тестирование по рискам', text + 'Рассчитайте риски, упорядочите функции и объясните, как распределить время тестирования.',
                                      'риски не рассчитаны либо порядок не обоснован',
                                      'риски рассчитаны, но порядок или распределение времени не объяснены',
                                      f'риски: {"; ".join(f"{f} — {score[f]}" for f in order)}; больше времени и глубины проверок получают функции с большим риском; низкорисковые проверяют поверхностно', ['testing']),
                            make_brief(rng, 'open_response', scenario, topic))
    return {'spec': 'qa', 'skills': ['testing'], 'tasks': out}


FAMILIES = [algo_binary_search, algo_nested_loops, algo_graph_bfs, algo_stack_queue, algo_sort_stability, algo_recursion,
            sql_window_rank, sql_count_distinct, js_destructure_spread, css_media_query, http_url_query, qa_risk_priority]
