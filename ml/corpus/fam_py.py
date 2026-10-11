"""Python-семейства: вывод и значения вычисляются выполнением фрагмента (exec) при сборке корпуса."""
import math

from .core import fmt_num, make_brief, multiple, numeric, open_task, pick_distinct, plural, single
from .runcode import py_out


def fence(code, lang='python'):
    return f'```{lang}\n{code.strip()}\n```'


def assemble(rng, *, lang, code, correct_out, wrong_outs, title, question, topic, truths, falses,
             num_q, num_v, num_unit, open_q, zero, fifty, hundred, skills, spec, scenario_intro, restr=''):
    scenario = f'{scenario_intro}\n{fence(code, lang)}'
    out = {}
    body = f'{scenario_intro}\n{fence(code, lang)}\n'
    wrongs = pick_distinct(rng, [correct_out], wrong_outs, 3)
    out['single_choice'] = (single(rng, title, body + question, correct_out, wrongs, skills),
                            make_brief(rng, 'single_choice', scenario, topic, restr))
    k = min(len(truths), rng.randint(2, 3))
    right = rng.sample(truths, k)
    bad = rng.sample(falses, min(len(falses), 2 if k == 2 else 1))
    out['multiple_choice'] = (multiple(rng, title, body + 'Какие утверждения верны? Выберите все верные.', right, bad, skills),
                              make_brief(rng, 'multiple_choice', scenario, topic, restr))
    out['numeric'] = (numeric(title, body + num_q, num_v, num_unit, skills),
                      make_brief(rng, 'numeric', scenario, topic, restr))
    out['open_response'] = (open_task(title, body + open_q, zero, fifty, hundred, skills),
                            make_brief(rng, 'open_response', scenario, topic, restr))
    return {'spec': spec, 'skills': skills, 'tasks': out}


def py_slice(rng, grade):
    n = rng.randint(6, 9)
    data = [rng.randint(1, 50) for _ in range(n)]
    start, stop = sorted(rng.sample(range(0, n + 1), 2))
    step = rng.choice([1, 2]) if grade == 'junior' else rng.choice([2, 3, -1, -2])
    if step < 0:
        start, stop = None, None
        expr = f'data[::{step}]'
        res = data[::step]
    else:
        expr = f'data[{start}:{stop}:{step}]' if step != 1 else f'data[{start}:{stop}]'
        res = data[start:stop:step]
    if not res:
        raise ValueError('пустой срез')
    code = f'data = {data}\nresult = {expr}\nprint(result)'
    assert py_out(code) == str(res)
    alts = [data[1:], data[:-1], data[::-1], data[::2], data[1::2], data[:3], data[-3:], data[1:-1]]
    wrongs = [str(a) for a in alts if a != res]
    truths = [f'результат содержит {plural(len(res), "элемент", "элемента", "элементов")}', f'первый элемент результата равен {res[0]}',
              f'исходный список data не изменяется']
    falses = [f'результат содержит {plural(len(res) + 1, "элемент", "элемента", "элементов")}', f'первый элемент результата равен {data[0] if data[0] != res[0] else data[-1]}',
              'срез изменяет исходный список data']
    sc = 'Дан фрагмент кода на Python.'
    return assemble(rng, lang='python', code=code, correct_out=str(res), wrong_outs=wrongs,
                    title='Срез списка в Python', question='Что выведет программа?', topic='срезах списка в Python',
                    truths=truths, falses=falses, num_q='Сколько элементов будет выведено?', num_v=len(res), num_unit='элементов',
                    open_q='Что выведет программа и как работает срез?',
                    zero='результат не назван либо срез истолкован неверно',
                    fifty=f'назван результат {res}, но нет объяснения границ и шага среза',
                    hundred=f'результат {res}; объяснено, что начало включается, конец не включается, шаг задаёт направление и пропуск; исходный список не меняется',
                    skills=['python'], spec=rng.choice(['backend', 'qa']), scenario_intro=sc,
                    restr='Не меняйте код.')


def py_alias(rng, grade):
    base = [rng.randint(1, 9) for _ in range(rng.randint(2, 3))]
    x, y = rng.randint(10, 20), rng.randint(21, 30)
    copy_form = rng.choice(['b = a[:]', 'b = list(a)', 'b = a.copy()'])
    code = f'a = {base}\nb = a\nb.append({x})\n{copy_form.replace("b =", "c =")}\nc.append({y})\nprint(a)\nprint(len(c))'
    out = py_out(code)
    a_res = base + [x]
    c_len = len(a_res) + 1
    assert out == f'{a_res}\n{c_len}'
    first = str(a_res)
    wrongs = [f'{base}\n{c_len}', f'{a_res}\n{c_len - 1}', f'{base}\n{len(base) + 1}', f'{a_res + [y]}\n{c_len}', f'{base}\n{c_len - 1}']
    truths = [f'a и b ссылаются на один и тот же список', f'после append в b список a содержит {plural(len(a_res), "элемент", "элемента", "элементов")}',
              f'c — независимая копия, добавление в c не меняет a']
    falses = [f'b — независимая копия списка a', f'append в c изменяет список a', f'список a остаётся равным {base}']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Ссылки и копии списков', question='Что выведет программа (две строки)?', topic='ссылках и копировании списков в Python',
                    truths=truths, falses=falses, num_q='Какое число выведет вторая строка?', num_v=c_len, num_unit='',
                    open_q='Что выведет программа и почему списки a и c ведут себя по-разному?',
                    zero='вывод не назван либо присваивание b = a считается копированием',
                    fifty=f'верно назван вывод {first}, но нет объяснения ссылок и копии',
                    hundred=f'первая строка {first}, вторая {c_len}; b = a даёт вторую ссылку на тот же список, а срез/копия создаёт независимый объект',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def py_mutable_default(rng, grade):
    item = [rng.randint(1, 9) for _ in range(3)]
    code = ('def collect(value, bucket=[]):\n    bucket.append(value)\n    return bucket\n\n'
            f'print(collect({item[0]}))\nprint(collect({item[1]}))\nprint(collect({item[2]}, []))')
    out = py_out(code)
    lines = out.split('\n')
    assert lines == [str([item[0]]), str([item[0], item[1]]), str([item[2]])]
    wrongs = [f'{[item[0]]}\n{[item[1]]}\n{[item[2]]}', f'{[item[0]]}\n{[item[0], item[1]]}\n{[item[0], item[1], item[2]]}',
              f'{[item[0]]}\n{[item[1]]}\n{[item[0], item[1], item[2]]}', f'{[item[0]]}\n{[item[0], item[1]]}\n{[item[0], item[2]]}']
    truths = ['изменяемое значение по умолчанию создаётся один раз при определении функции', f'второй вызов вернёт список из двух элементов',
              'третий вызов с явным пустым списком не затрагивает накопленный список']
    falses = ['при каждом вызове без второго аргумента создаётся новый пустой список', 'третий вызов вернёт список из трёх элементов',
              'второй вызов вернёт список из одного элемента']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Изменяемый аргумент по умолчанию', question='Что выведет программа (три строки)?',
                    topic='изменяемых значениях аргументов по умолчанию в Python',
                    truths=truths, falses=falses, num_q='Сколько элементов будет в списке, выведенном второй строкой?', num_v=2, num_unit='элементов',
                    open_q='Что выведет программа, почему и как исправить функцию?',
                    zero='вывод не назван либо поведение объяснено случайностью',
                    fifty=f'верно назван вывод, но нет причины или исправления',
                    hundred=f'вывод: {lines[0]}, {lines[1]}, {lines[2]}; список по умолчанию создаётся один раз при определении функции; исправление — bucket=None и создание списка внутри функции',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def py_arith(rng, grade):
    a = rng.randint(7, 40)
    b = rng.randint(2, 6)
    neg = rng.choice([True, False])
    if neg:
        a = -a
    q, r = a // b, a % b
    t = int(a / b)
    code = f'a = {a}\nb = {b}\nprint(a // b)\nprint(a % b)\nprint(int(a / b))'
    out = py_out(code)
    assert out == f'{q}\n{r}\n{t}'
    wrongs = [f'{t}\n{a - t * b}\n{q}', f'{q}\n{a - t * b}\n{t}', f'{q + 1}\n{r}\n{t}', f'{t}\n{r}\n{q}', f'{q}\n{r + 1}\n{t + 1}']
    truths = [f'a // b равно {q}', f'a % b равно {r}', f'int(a / b) равно {t}']
    falses = [f'a // b равно {t if t != q else q + 1}', f'a % b равно {a - t * b if a - t * b != r else r + 1}', f'int(a / b) равно {q if q != t else t + 1}']
    if q == t:
        falses = [f'a // b равно {q + 1}', f'a % b равно {r + 1}', f'int(a / b) равно {t - 1}']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Деление и остаток в Python', question='Что выведет программа (три строки)?',
                    topic='целочисленном делении и остатке в Python',
                    truths=truths, falses=falses, num_q='Чему равно значение a % b?', num_v=r, num_unit='',
                    open_q='Что выведет программа и чем // отличается от int(a / b) для отрицательных чисел?',
                    zero='значения не вычислены либо // считается отбрасыванием дробной части для любых знаков',
                    fifty=f'верно вычислены {q}, {r} и {t}, но нет объяснения различия округления вниз и усечения',
                    hundred=f'вывод {q}, {r}, {t}; // округляет вниз к меньшему целому, int() усекает к нулю; остаток % согласован с // (a = b*(a//b) + a%b)',
                    skills=['python'], spec=rng.choice(['backend', 'qa']), scenario_intro='Дан фрагмент кода на Python.')


def py_round_banker(rng, grade):
    vals = [rng.choice([0.5, 1.5, 2.5, 3.5, 4.5]) for _ in range(3)]
    vals = list(dict.fromkeys(vals))
    while len(vals) < 3:
        vals.append(rng.choice([0.5, 1.5, 2.5, 3.5, 4.5, 5.5]))
        vals = list(dict.fromkeys(vals))
    code = f'values = {vals}\nprint([round(v) for v in values])'
    out = py_out(code)
    res = [round(v) for v in vals]
    up = [int(v + 0.5) for v in vals]
    wrongs = [str(up), str([math.floor(v) for v in vals]), str([math.ceil(v) for v in vals]), str([int(v) for v in vals][::-1])]
    truths = ['round() в Python 3 округляет половины к ближайшему чётному целому', f'результат содержит {plural(len(res), "элемент", "элемента", "элементов")}',
              f'round({vals[0]}) равно {res[0]}']
    falses = ['round() всегда округляет половины вверх', f'round({vals[0]}) равно {up[0] if up[0] != res[0] else res[0] + 1}', 'round() возвращает число с плавающей точкой для одного аргумента']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Округление round() в Python', question='Что выведет программа?', topic='округлении round() в Python',
                    truths=truths, falses=falses, num_q=f'Чему равно round({vals[0]})?', num_v=res[0], num_unit='',
                    open_q='Что выведет программа и по какому правилу округляются половины?',
                    zero='вывод не назван либо принято школьное округление половин вверх',
                    fifty=f'верно назван вывод {out}, но правило не названо',
                    hundred=f'вывод {out}; в Python 3 round() округляет половины к ближайшему чётному (банковское округление), а не всегда вверх',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def py_dict_set(rng, grade):
    words = rng.sample(['api', 'sql', 'http', 'test', 'css', 'git', 'json', 'ssh'], 6)
    a = words[:4]
    b = words[2:]
    code = f'a = set({a})\nb = set({b})\nprint(len(a & b))\nprint(len(a | b))\nprint(len(a - b))'
    sa, sb = set(a), set(b)
    out = f'{len(sa & sb)}\n{len(sa | sb)}\n{len(sa - sb)}'
    assert py_out(code) == out
    i, u, d = len(sa & sb), len(sa | sb), len(sa - sb)
    wrongs = [f'{u}\n{i}\n{d}', f'{i}\n{u}\n{len(sb - sa) + 1}', f'{i + 1}\n{u}\n{d}', f'{i}\n{u + 1}\n{d + 1}', f'{d}\n{u}\n{i}']
    truths = [f'пересечение содержит {plural(i, "элемент", "элемента", "элементов")}', f'объединение содержит {plural(u, "элемент", "элемента", "элементов")}',
              f'разность a - b содержит {plural(d, "элемент", "элемента", "элементов")}']
    falses = [f'пересечение содержит {plural(i + 1, "элемент", "элемента", "элементов")}', f'объединение содержит {plural(len(a) + len(b), "элемент", "элемента", "элементов")}',
              f'разность a - b содержит {plural(d + 1, "элемент", "элемента", "элементов")}']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Операции над множествами', question='Что выведет программа (три строки)?', topic='операциях над множествами в Python',
                    truths=truths, falses=falses, num_q='Сколько элементов в объединении a | b?', num_v=u, num_unit='элементов',
                    open_q='Что выведет программа и как связаны размеры пересечения, объединения и разности?',
                    zero='значения не вычислены либо дубликаты считаются отдельно',
                    fifty=f'верно вычислены {i}, {u}, {d}, но нет объяснения связи',
                    hundred=f'вывод {i}, {u}, {d}; элементы множества уникальны; |a|+|b| = |a∪b| + |a∩b|, поэтому общие элементы не считаются дважды',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def py_comprehension(rng, grade):
    data = [rng.randint(1, 30) for _ in range(rng.randint(6, 9))]
    m = rng.choice([2, 3, 5])
    t = rng.randint(5, 18)
    code = f'data = {data}\nresult = [x * 2 for x in data if x % {m} == 0 and x > {t}]\nprint(result)\nprint(sum(result))'
    out = py_out(code)
    res = [x * 2 for x in data if x % m == 0 and x > t]
    if not res or len(res) == len(data):
        raise ValueError('вырожденно')
    wrongs = [f'{[x for x in data if x % m == 0 and x > t]}\n{sum(x for x in data if x % m == 0 and x > t)}',
              f'{[x * 2 for x in data if x % m == 0 or x > t]}\n{sum(x * 2 for x in data if x % m == 0 or x > t)}',
              f'{[x * 2 for x in data if x % m == 0]}\n{sum(x * 2 for x in data if x % m == 0)}',
              f'{res}\n{sum(res) // 2}', f'{[x * 2 for x in data if x > t]}\n{sum(x * 2 for x in data if x > t)}']
    truths = [f'в result {plural(len(res), "элемент", "элемента", "элементов")}', f'sum(result) равно {sum(res)}', 'условия в if объединены через and, поэтому нужны оба']
    falses = [f'в result {plural(len(res) + 1, "элемент", "элемента", "элементов")}', f'sum(result) равно {sum(res) // 2}', 'достаточно выполнения любого из двух условий']
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Списковое включение с условием', question='Что выведет программа (две строки)?',
                    topic='списковых включениях с условием в Python',
                    truths=truths, falses=falses, num_q='Чему равно sum(result)?', num_v=sum(res), num_unit='',
                    open_q='Что выведет программа и в каком порядке применяются фильтр и преобразование?',
                    zero='вывод не назван либо условие применено после умножения',
                    fifty=f'верно назван список {res}, но не объяснён порядок фильтра и преобразования',
                    hundred=f'вывод {res} и {sum(res)}; if отбирает элементы по исходному x (кратность {m} и x > {t}), затем выражение x * 2 преобразует каждый отобранный',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


def py_exceptions(rng, grade):
    n = rng.randint(2, 6)
    d = rng.choice([0, 0, 2])
    code = ('def run(x):\n    try:\n        print("start")\n        r = 10 // x\n        print("ok", r)\n    except ZeroDivisionError:\n        print("zero")\n'
            '    finally:\n        print("end")\n\n' + f'run({d})')
    out = py_out(code)
    lines = out.split('\n')
    wrongs = ['start\nok 5\nend' if d == 0 else 'start\nzero\nend', 'start\nzero', 'start\nzero\nend\nok 5', 'zero\nend', 'start\nend', 'start\nok 5\nzero\nend']
    truths = ['блок finally выполняется независимо от того, было ли исключение', f'вывод состоит из {plural(len(lines), "строки", "строк", "строк")}' if False else f'последняя выведенная строка — end',
              'первой выводится строка start']
    falses = ['finally выполняется только при отсутствии исключения', 'первой выводится строка end', 'исключение не перехватывается блоком except']
    if d == 0:
        truths.append('ZeroDivisionError перехватывается блоком except')
    else:
        falses.append('ZeroDivisionError перехватывается блоком except')
    return assemble(rng, lang='python', code=code, correct_out=out, wrong_outs=wrongs,
                    title='Порядок try/except/finally', question='Что выведет программа?', topic='порядке выполнения try, except и finally в Python',
                    truths=truths[:3], falses=falses[:3], num_q='Сколько строк выведет программа?', num_v=len(lines), num_unit='строк',
                    open_q='Что выведет программа и в каком порядке выполняются блоки?',
                    zero='вывод не назван либо finally пропущен',
                    fifty=f'верно назван вывод, но не объяснён порядок try, except и finally',
                    hundred=f'вывод: {", ".join(lines)}; try выполняется до исключения, затем except, finally выполняется всегда',
                    skills=['python'], spec='backend', scenario_intro='Дан фрагмент кода на Python.')


FAMILIES = [py_slice, py_alias, py_mutable_default, py_arith, py_round_banker, py_dict_set, py_comprehension, py_exceptions]
