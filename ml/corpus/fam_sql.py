"""SQL-семейства: истина вычисляется выполнением запросов в sqlite3 (SQLite-диалект)."""
import math
import sqlite3

from .core import fmt_num, make_brief, multiple, numeric, open_task, pick_distinct, plural, single

TABLES = [
    ('readings', 'value', 'показаний датчика'), ('orders', 'amount', 'заказов'),
    ('scores', 'points', 'оценок'), ('payments', 'sum_rub', 'платежей'),
    ('measurements', 'level', 'измерений'), ('tickets', 'hours', 'заявок'),
    ('sales', 'qty', 'продаж'), ('requests', 'latency_ms', 'запросов'),
]


def run(sql, setup=()):
    con = sqlite3.connect(':memory:')
    for statement in setup:
        con.execute(statement)
    rows = con.execute(sql).fetchall()
    con.close()
    return rows


def rows_text(table, column, values):
    return ', '.join(f'{column}={"NULL" if v is None else v}' for v in values)


def sql_null_aggregates(rng, grade):
    table, column, _ = rng.choice(TABLES)
    n = rng.randint(3, 4) if grade == 'junior' else rng.randint(5, 7)
    values = [rng.randint(1, 40) for _ in range(n)]
    for index in rng.sample(range(n), rng.randint(1, max(1, n // 3))):
        values[index] = None
    if all(v is None for v in values) or sum(v is None for v in values) == 0:
        values[0], values[-1] = 5, None
    setup = [f'CREATE TABLE {table}({column} INTEGER)'] + [
        f'INSERT INTO {table} VALUES ({"NULL" if v is None else v})' for v in values]
    count_col = run(f'SELECT COUNT({column}) FROM {table}', setup)[0][0]
    count_all = run('SELECT COUNT(*) FROM ' + table, setup)[0][0]
    total = run(f'SELECT SUM({column}) FROM {table}', setup)[0][0]
    avg = run(f'SELECT AVG({column}) FROM {table}', setup)[0][0]
    avg_text = fmt_num(round(avg, 2))
    wrong_avg = fmt_num(round(total / count_all, 2))
    scenario = (f'В SQLite есть таблица {table}({column} INTEGER) с {n} строками: '
                f'{rows_text(table, column, values)}.')
    data = (f'В таблице {table}({column} INTEGER) {plural(n, 'строка', 'строки', 'строк')}: {rows_text(table, column, values)}. ')
    pairs = f'COUNT({column}) и COUNT(*)'
    ask = rng.choice(['count_pair', 'sum', 'avg', 'diff'])
    topic = rng.choice([f'различии {pairs} при значениях NULL', f'работе агрегатных функций с NULL в столбце {column}'])
    restr = rng.choice(['Покажите данные в условии; не добавляйте строки, WHERE и другие диалекты SQL.',
                        'Данные должны быть в условии; не меняйте таблицу.', ''])
    out = {}
    # single
    prompt = data + f'Какие значения вернёт запрос SELECT COUNT({column}), COUNT(*) FROM {table}?'
    right = f'{count_col} и {count_all}'
    wrongs = pick_distinct(rng, [right], [f'{count_all} и {count_col}', f'{count_all} и {count_all}',
                                          f'{count_col} и {count_col}', f'{count_col} и {count_all - 1}',
                                          f'{count_all + 1} и {count_all}'], 3)
    out['single_choice'] = (single(rng, f'COUNT({column}) и COUNT(*) в SQLite', prompt, right, wrongs, ['sql']),
                            make_brief(rng, 'single_choice', scenario, topic, restr))
    # multiple
    true_statements = [f'COUNT(*) вернёт {count_all}', f'COUNT({column}) вернёт {count_col}',
                       f'SUM({column}) вернёт {total}', f'AVG({column}) вернёт {avg_text}']
    false_statements = [f'COUNT({column}) вернёт {count_all}', f'COUNT(*) вернёт {count_col}',
                        f'AVG({column}) вернёт {wrong_avg}', f'SUM({column}) вернёт NULL']
    if wrong_avg == avg_text:
        false_statements.remove(f'AVG({column}) вернёт {wrong_avg}')
    k = rng.randint(2, 3)
    right_list = rng.sample(true_statements, k)
    wrong_list = rng.sample(false_statements, min(len(false_statements), 4 - k if k == 3 else 2))
    prompt = data + f'Какие утверждения о результатах запросов к таблице {table} верны? Выберите все верные.'
    out['multiple_choice'] = (multiple(rng, f'Агрегаты и NULL в таблице {table}', prompt, right_list, wrong_list, ['sql']),
                              make_brief(rng, 'multiple_choice', scenario, topic, restr))
    # numeric
    if ask == 'count_pair':
        q, value, unit = f'Сколько строк вернёт COUNT({column})?', count_col, 'строк'
    elif ask == 'sum':
        q, value, unit = f'Чему равен результат SELECT SUM({column}) FROM {table}?', total, ''
    elif ask == 'avg':
        q, value, unit = f'Чему равен результат SELECT AVG({column}) FROM {table}? Округлите до сотых.', round(avg, 2), ''
    else:
        q, value, unit = (f'На сколько COUNT(*) больше, чем COUNT({column})?', count_all - count_col, '')
    out['numeric'] = (numeric(f'Агрегат по столбцу {column} с NULL', data + q, value, unit, ['sql']),
                      make_brief(rng, 'numeric', scenario, topic, restr))
    # open
    prompt = data + (f'Назовите результаты COUNT({column}), COUNT(*), SUM({column}) и AVG({column}) '
                     f'и объясните, как NULL влияет на каждый из них.')
    rubric_zero = 'значения не названы либо считаются так, будто NULL участвует в агрегатах'
    rubric_fifty = f'верно названы COUNT({column})={count_col} и COUNT(*)={count_all}, но нет SUM и AVG либо не объяснена роль NULL'
    rubric_hundred = (f'COUNT({column})={count_col}, COUNT(*)={count_all}, SUM={total}, AVG={avg_text}; '
                      f'объяснено, что NULL пропускается агрегатами по столбцу, а COUNT(*) считает все строки')
    out['open_response'] = (open_task(f'Объясните агрегаты и NULL в {table}', prompt, rubric_zero, rubric_fifty,
                                      rubric_hundred, ['sql']),
                            make_brief(rng, 'open_response', scenario, topic, restr))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def sql_filter_count(rng, grade):
    table = rng.choice(['users', 'orders', 'tickets', 'items'])
    status_pool = ['new', 'paid', 'failed', 'done'] if table != 'users' else ['active', 'blocked', 'new']
    n = rng.randint(5, 6) if grade == 'junior' else rng.randint(7, 9)
    rows = [(i + 1, rng.choice(status_pool), rng.randint(1, 30)) for i in range(n)]
    setup = [f'CREATE TABLE {table}(id INTEGER, status TEXT, qty INTEGER)'] + [
        f"INSERT INTO {table} VALUES ({a}, '{b}', {c})" for a, b, c in rows]
    for _ in range(60):
        status = rng.choice(status_pool)
        limit = rng.randint(5, 20)
        cond = rng.choice(['and', 'or'])
        where = f"status = '{status}' {cond.upper()} qty > {limit}"
        result = run(f'SELECT COUNT(*) FROM {table} WHERE {where}', setup)[0][0]
        if 1 <= result < n:
            break
    else:
        raise ValueError('нет подходящего условия')
    ids = [r[0] for r in run(f'SELECT id FROM {table} WHERE {where} ORDER BY id', setup)]
    wrong_op = 'or' if cond == 'and' else 'and'
    wrong_count = run(f"SELECT COUNT(*) FROM {table} WHERE status = '{status}' {wrong_op.upper()} qty > {limit}", setup)[0][0]
    data_rows = '; '.join(f'({a}, {b}, {c})' for a, b, c in rows)
    scenario = (f'В SQLite есть таблица {table}(id, status, qty) со строками (id, status, qty): {data_rows}.')
    data = f'Таблица {table}(id, status, qty) содержит строки (id, status, qty): {data_rows}. '
    topic = 'фильтрации строк условием WHERE с AND и OR'
    restr = rng.choice(['Данные покажите в условии; другие строки не добавляйте.', ''])
    out = {}
    q = f"Сколько строк вернёт запрос SELECT * FROM {table} WHERE {where}?"
    out['numeric'] = (numeric(f'Строки по условию WHERE в {table}', data + q, result, 'строк', ['sql']),
                      make_brief(rng, 'numeric', scenario, topic, restr))
    id_text = lambda xs: ', '.join(map(str, xs)) if xs else 'ни одной строки'
    right = f'id: {id_text(ids)}'
    pool_ids = [sorted(set(ids) ^ {rng.randint(1, n)}) for _ in range(12)]
    pool = [f'id: {id_text(x)}' for x in pool_ids]
    other = [r[0] for r in run(f"SELECT id FROM {table} WHERE status = '{status}' {wrong_op.upper()} qty > {limit} ORDER BY id", setup)]
    pool.append(f'id: {id_text(other)}')
    wrongs = pick_distinct(rng, [right], pool, 3)
    prompt = data + f"Какие id вернёт запрос SELECT id FROM {table} WHERE {where} ORDER BY id?"
    out['single_choice'] = (single(rng, f'Результат запроса с {cond.upper()} в {table}', prompt, right, wrongs, ['sql']),
                            make_brief(rng, 'single_choice', scenario, topic, restr))
    # multiple: какие строки попадают
    inside = [r for r in ids]
    outside = [r for r in range(1, n + 1) if r not in inside]
    if len(inside) >= 2 and len(outside) >= 1:
        right_list = [f'строка с id={i}' for i in rng.sample(inside, min(len(inside), rng.randint(2, 3)))]
        wrong_list = [f'строка с id={i}' for i in rng.sample(outside, min(len(outside), 2))]
        prompt = data + f"Какие строки попадут в результат запроса SELECT * FROM {table} WHERE {where}? Выберите все верные."
        out['multiple_choice'] = (multiple(rng, f'Строки по условию {cond.upper()}', prompt, right_list, wrong_list, ['sql']),
                                  make_brief(rng, 'multiple_choice', scenario, topic, restr))
    prompt = data + (f"Определите, какие строки вернёт запрос SELECT * FROM {table} WHERE {where}, "
                     f"и объясните, чем результат отличился бы при замене {cond.upper()} на {wrong_op.upper()}.")
    out['open_response'] = (open_task(f'Условие WHERE с {cond.upper()}', prompt,
                                      'строки не определены или условие применено неверно',
                                      f'верно определено число строк ({result}), но не объяснено различие AND и OR',
                                      f'перечислены id: {id_text(ids)}; результат равен {plural(result, 'строка', 'строки', 'строк')}; объяснено, что с {wrong_op.upper()} вернулось бы {plural(wrong_count, 'строка', 'строки', 'строк')}',
                                      ['sql']),
                            make_brief(rng, 'open_response', scenario, topic, restr))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def sql_group_having(rng, grade):
    table = 'orders'
    customers = rng.sample(['Анна', 'Борис', 'Вера', 'Глеб', 'Дарья'], rng.randint(3, 4))
    n = rng.randint(6, 8) if grade == 'junior' else rng.randint(8, 11)
    rows = [(rng.choice(customers), rng.randint(1, 9) * 100) for _ in range(n)]
    setup = [f'CREATE TABLE {table}(customer TEXT, amount INTEGER)'] + [
        f"INSERT INTO {table} VALUES ('{c}', {a})" for c, a in rows]
    totals = sorted({sum(a for c2, a in rows if c2 == c) for c in {c for c, _ in rows}})
    if len(totals) < 2:
        raise ValueError('вырожденная выборка')
    threshold = totals[rng.randint(0, len(totals) - 2)]
    having_sum = run(f'SELECT customer, SUM(amount) FROM {table} GROUP BY customer HAVING SUM(amount) > {threshold} ORDER BY customer', setup)
    groups = run(f'SELECT customer, SUM(amount), COUNT(*) FROM {table} GROUP BY customer ORDER BY customer', setup)
    data_rows = '; '.join(f'({c}, {a})' for c, a in rows)
    data = f'Таблица {table}(customer, amount) содержит строки: {data_rows}. '
    scenario = f'В SQLite есть таблица {table}(customer, amount) со строками (customer, amount): {data_rows}.'
    topic = 'группировке GROUP BY и условии HAVING'
    restr = rng.choice(['Данные покажите в условии; не меняйте таблицу.', ''])
    out = {}
    q = f'Сколько строк вернёт запрос SELECT customer, SUM(amount) FROM {table} GROUP BY customer HAVING SUM(amount) > {threshold}?'
    out['numeric'] = (numeric(f'Группы с HAVING по сумме в {table}', data + q, len(having_sum), 'строк', ['sql']),
                      make_brief(rng, 'numeric', scenario, topic, restr))
    names = [c for c, _ in having_sum]
    all_names = [g[0] for g in groups]
    right = ', '.join(names) if names else 'ни один покупатель'
    pool = []
    for _ in range(14):
        sub = rng.sample(all_names, rng.randint(1, len(all_names)))
        pool.append(', '.join(sorted(sub)))
    pool.append(', '.join(all_names))
    pool = [p for p in pool if p != right]
    right_sorted = ', '.join(sorted(names)) if names else right
    wrongs = pick_distinct(rng, [right_sorted], pool, 3)
    prompt = data + f'Каких покупателей вернёт запрос SELECT customer FROM {table} GROUP BY customer HAVING SUM(amount) > {threshold} ORDER BY customer?'
    out['single_choice'] = (single(rng, 'Покупатели по HAVING SUM', prompt, right_sorted, wrongs, ['sql']),
                            make_brief(rng, 'single_choice', scenario, topic, restr))
    sums = {g[0]: g[1] for g in groups}
    cnts = {g[0]: g[2] for g in groups}
    who = rng.choice(all_names)
    other = rng.choice([x for x in all_names if x != who])
    out_q = f'Чему равна сумма amount для покупателя {who} в результате GROUP BY customer?'
    out['numeric_alt'] = (numeric(f'Сумма по группе {who}', data + out_q, sums[who], '', ['sql']),
                          make_brief(rng, 'numeric', scenario, topic, restr))
    prompt = data + f'Опишите результат GROUP BY customer с SUM(amount) и объясните, чем HAVING отличается от WHERE в этом запросе при пороге {threshold}.'
    listing = '; '.join(f'{c}: {s}' for c, s, _ in groups)
    out['open_response'] = (open_task('GROUP BY и HAVING', prompt,
                                      'суммы по покупателям не вычислены либо HAVING описан как фильтр строк до группировки',
                                      'верно посчитаны суммы по группам, но нет объяснения различия WHERE и HAVING',
                                      f'суммы по группам: {listing}; в результат при пороге {threshold} входят {plural(len(having_sum), 'группа', 'группы', 'групп')}; объяснено, что WHERE фильтрует строки до группировки, а HAVING — группы после агрегата',
                                      ['sql']),
                            make_brief(rng, 'open_response', scenario, topic, restr))
    wrong_stmt = [f'HAVING применяется до группировки строк', 'WHERE может ссылаться на SUM(amount) в этом запросе']
    ok_stmt = [f'группа {who} содержит {plural(cnts[who], 'строка', 'строки', 'строк')}', f'сумма группы {other} равна {sums[other]}']
    wrong_stmt.append(f'сумма группы {who} равна {sums[who] + 100}')
    out['multiple_choice'] = (multiple(rng, 'Верные утверждения о группах', data + f'Какие утверждения о запросе SELECT customer, SUM(amount) FROM {table} GROUP BY customer верны? Выберите все верные.',
                                       ok_stmt, rng.sample(wrong_stmt, 2), ['sql']),
                              make_brief(rng, 'multiple_choice', scenario, topic, restr))
    del out['numeric_alt']
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def sql_join_counts(rng, grade):
    users = rng.sample(['Анна', 'Борис', 'Вера', 'Глеб', 'Дарья'], rng.randint(3, 4))
    orders = [(i + 1, rng.choice(users + [None, 'Игорь'])) for i in range(rng.randint(4, 6))]
    # заказы ссылаются на пользователей по имени; Игорь и None — без пары
    setup = ['CREATE TABLE users(name TEXT)', 'CREATE TABLE orders(id INTEGER, user_name TEXT)'] + [
        f"INSERT INTO users VALUES ('{u}')" for u in users] + [
        f"INSERT INTO orders VALUES ({i}, {'NULL' if u is None else repr(u)})" for i, u in orders]
    inner = run('SELECT COUNT(*) FROM users u JOIN orders o ON o.user_name = u.name', setup)[0][0]
    left = run('SELECT COUNT(*) FROM users u LEFT JOIN orders o ON o.user_name = u.name', setup)[0][0]
    left_null = run('SELECT COUNT(*) FROM users u LEFT JOIN orders o ON o.user_name = u.name WHERE o.id IS NULL', setup)[0][0]
    cross = len(users) * len(orders)
    data = (f'Таблица users(name): {", ".join(users)}. Таблица orders(id, user_name): '
            + '; '.join(f'({i}, {"NULL" if u is None else u})' for i, u in orders) + '. ')
    scenario = ('В SQLite две таблицы. ' + data.strip())
    topic = 'различии INNER JOIN и LEFT JOIN по числу строк'
    restr = rng.choice(['Данные оставьте в условии; другие строки не добавляйте.', ''])
    out = {}
    out['numeric'] = (numeric('Число строк INNER JOIN', data + 'Сколько строк вернёт SELECT * FROM users u JOIN orders o ON o.user_name = u.name?',
                              inner, 'строк', ['sql']), make_brief(rng, 'numeric', scenario, topic, restr))
    right = f'INNER JOIN: {inner}, LEFT JOIN: {left}'
    pool = [f'INNER JOIN: {a}, LEFT JOIN: {b}' for a, b in [(left, inner), (inner, inner), (cross, left), (inner, cross), (inner + 1, left), (left, left + 1), (inner, left - 1)]]
    wrongs = pick_distinct(rng, [right], pool, 3)
    out['single_choice'] = (single(rng, 'INNER JOIN и LEFT JOIN: число строк', data + 'Сколько строк вернут запросы с INNER JOIN и LEFT JOIN по условию o.user_name = u.name (users слева)?',
                                   right, wrongs, ['sql']), make_brief(rng, 'single_choice', scenario, topic, restr))
    ok = [f'LEFT JOIN вернёт {plural(left, 'строка', 'строки', 'строк')}', f'в LEFT JOIN o.id равен NULL у {left_null} из {len(users)} пользователей' if left_null else 'каждый пользователь из users имеет хотя бы один заказ']
    bad = [f'INNER JOIN вернёт {plural(len(users) * len(orders), 'строка', 'строки', 'строк')}', 'строки orders с user_name NULL попадут в INNER JOIN', f'LEFT JOIN вернёт {plural(left + 1, 'строка', 'строки', 'строк')}']
    if left_null == 0:
        ok = [f'LEFT JOIN вернёт {plural(left, 'строка', 'строки', 'строк')}', f'INNER JOIN вернёт {plural(inner, 'строка', 'строки', 'строк')}']
    out['multiple_choice'] = (multiple(rng, 'Верные утверждения о JOIN', data + 'Какие утверждения о запросах по условию o.user_name = u.name верны? Выберите все верные.',
                                       ok, rng.sample(bad, 2), ['sql']), make_brief(rng, 'multiple_choice', scenario, topic, restr))
    out['open_response'] = (open_task('INNER JOIN и LEFT JOIN', data + 'Объясните, сколько строк вернут INNER JOIN и LEFT JOIN по условию o.user_name = u.name и почему результаты различаются.',
                                      'числа строк не названы либо JOIN объяснены как одинаковые',
                                      f'верно назван результат INNER JOIN ({inner}), но нет LEFT JOIN или причины различия',
                                      f'INNER JOIN вернёт {plural(inner, 'строка', 'строки', 'строк')}, LEFT JOIN — {left}; LEFT JOIN сохраняет все строки users, даже без пары, подставляя NULL; строки orders без пользователя в users не учитываются',
                                      ['sql']), make_brief(rng, 'open_response', scenario, topic, restr))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def sql_dml_affected(rng, grade):
    n = rng.randint(5, 7)
    rows = [(i + 1, rng.choice(['new', 'done', 'failed']), rng.randint(1, 9)) for i in range(n)]
    setup = ['CREATE TABLE jobs(id INTEGER, status TEXT, retries INTEGER)'] + [
        f"INSERT INTO jobs VALUES ({a}, '{b}', {c})" for a, b, c in rows]
    for _ in range(60):
        status = rng.choice(['new', 'done', 'failed'])
        limit = rng.randint(2, 6)
        con = sqlite3.connect(':memory:')
        for s in setup:
            con.execute(s)
        upd = con.execute(f"UPDATE jobs SET status = 'archived' WHERE status = '{status}' AND retries < {limit}").rowcount
        dele = con.execute("DELETE FROM jobs WHERE status = 'archived'").rowcount
        remain = con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        con.close()
        if 1 <= upd < n:
            break
    else:
        raise ValueError('нет подходящего условия')
    data = 'Таблица jobs(id, status, retries) содержит строки: ' + '; '.join(f'({a}, {b}, {c})' for a, b, c in rows) + '. '
    scenario = 'В SQLite есть таблица jobs(id, status, retries) со строками (id, status, retries): ' + '; '.join(f'({a}, {b}, {c})' for a, b, c in rows) + '.'
    topic = 'числе строк, затронутых UPDATE и DELETE'
    restr = rng.choice(['Данные покажите в условии.', 'Не добавляйте другие строки и таблицы.', ''])
    seq = (f"Выполнены по порядку: UPDATE jobs SET status = 'archived' WHERE status = '{status}' AND retries < {limit}; "
           "затем DELETE FROM jobs WHERE status = 'archived'. ")
    out = {}
    out['numeric'] = (numeric('Строки после UPDATE и DELETE', data + seq + 'Сколько строк осталось в таблице jobs?', remain, 'строк', ['sql']),
                      make_brief(rng, 'numeric', scenario, topic, restr))
    right = f'UPDATE изменит {upd}, DELETE удалит {dele}'
    pool = [f'UPDATE изменит {a}, DELETE удалит {b}' for a, b in [(upd, 0), (upd + 1, upd + 1), (n - upd, n - upd), (upd, upd + 1), (remain, dele), (n, n), (dele + 1, dele)]]
    wrongs = pick_distinct(rng, [right], pool, 3)
    out['single_choice'] = (single(rng, 'Затронутые строки UPDATE и DELETE', data + seq + 'Сколько строк затронет каждая из двух команд?', right, wrongs, ['sql']),
                            make_brief(rng, 'single_choice', scenario, topic, restr))
    ok = [f'после обеих команд в таблице останется {plural(remain, 'строка', 'строки', 'строк')}', f'UPDATE изменит {plural(upd, 'строка', 'строки', 'строк')}']
    bad = [f'DELETE удалит {plural(x, 'строка', 'строки', 'строк')}' for x in {n, upd + 1} if x != dele]
    bad += [f'UPDATE изменит {plural(x, 'строка', 'строки', 'строк')}' for x in {upd + 1, n} if x != upd]
    bad += [f'после обеих команд в таблице останется {plural(x, 'строка', 'строки', 'строк')}' for x in {n, remain + 1} if x != remain]
    out['multiple_choice'] = (multiple(rng, 'Верные утверждения об UPDATE и DELETE', data + seq + 'Какие утверждения верны? Выберите все верные.',
                                       ok, rng.sample(sorted(bad), 2), ['sql']),
                              make_brief(rng, 'multiple_choice', scenario, topic, restr))
    out['open_response'] = (open_task('UPDATE и DELETE: последствия', data + seq + 'Опишите, сколько строк изменит UPDATE, сколько удалит DELETE и сколько останется.',
                                      'ни одно число не названо либо порядок команд не учтён',
                                      f'верно назван результат UPDATE ({upd}), но не посчитано удаление или остаток',
                                      f'UPDATE изменит {plural(upd, 'строка', 'строки', 'строк')}, DELETE удалит {dele}, останется {remain}; DELETE видит строки, изменённые предыдущим UPDATE',
                                      ['sql']), make_brief(rng, 'open_response', scenario, topic, restr))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


def sql_not_in_null(rng, grade):
    values = rng.sample(range(1, 12), rng.randint(3, 4))
    sub = rng.sample(values, 2) + [None]
    setup = ['CREATE TABLE t(x INTEGER)', 'CREATE TABLE s(y INTEGER)'] + [f'INSERT INTO t VALUES ({v})' for v in values] + [
        f'INSERT INTO s VALUES ({"NULL" if v is None else v})' for v in sub]
    not_in = run('SELECT COUNT(*) FROM t WHERE x NOT IN (SELECT y FROM s)', setup)[0][0]
    not_in_nonnull = run('SELECT COUNT(*) FROM t WHERE x NOT IN (SELECT y FROM s WHERE y IS NOT NULL)', setup)[0][0]
    in_count = run('SELECT COUNT(*) FROM t WHERE x IN (SELECT y FROM s)', setup)[0][0]
    data = (f'Таблица t(x) содержит значения {", ".join(map(str, values))}. Таблица s(y) содержит значения '
            + ', '.join('NULL' if v is None else str(v) for v in sub) + '. ')
    scenario = 'В SQLite есть таблицы. ' + data.strip()
    topic = 'поведении NOT IN и IN при наличии NULL в подзапросе'
    restr = rng.choice(['Данные оставьте в условии.', 'Не добавляйте другие значения.', ''])
    out = {}
    out['numeric'] = (numeric('NOT IN и NULL', data + 'Сколько строк вернёт SELECT x FROM t WHERE x NOT IN (SELECT y FROM s)?', not_in, 'строк', ['sql']),
                      make_brief(rng, 'numeric', scenario, topic, restr))
    right = f'{plural(not_in, 'строка', 'строки', 'строк')}: NULL в подзапросе делает условие NOT IN неопределённым'
    wrongs = [f'{plural(not_in_nonnull, 'строка', 'строки', 'строк')}: NULL в подзапросе игнорируется',
              f'{plural(len(values), 'строка', 'строки', 'строк')}: все значения t не равны значениям s',
              f'{plural(in_count, 'строка', 'строки', 'строк')}: NOT IN работает как IN']
    wrongs = pick_distinct(rng, [right], wrongs + [f'{plural(max(len(values) - 1, 0), 'строка', 'строки', 'строк')}: NULL считается числом 0'], 3)
    out['single_choice'] = (single(rng, 'NOT IN с NULL в подзапросе', data + 'Сколько строк вернёт SELECT x FROM t WHERE x NOT IN (SELECT y FROM s) и почему?', right, wrongs, ['sql']),
                            make_brief(rng, 'single_choice', scenario, topic, restr))
    ok = [f'SELECT x FROM t WHERE x IN (SELECT y FROM s) вернёт {plural(in_count, 'строка', 'строки', 'строк')}',
          f'запрос NOT IN с фильтром y IS NOT NULL в подзапросе вернёт {plural(not_in_nonnull, 'строка', 'строки', 'строк')}']
    bad = [f'исходный запрос NOT IN вернёт {plural(not_in_nonnull, 'строка', 'строки', 'строк')}' if not_in_nonnull != not_in else 'исходный запрос NOT IN вернёт все строки t',
           'NULL в подзапросе всегда считается равным нулю', 'NOT IN всегда возвращает строки, которых нет в подзапросе, независимо от NULL']
    out['multiple_choice'] = (multiple(rng, 'IN, NOT IN и NULL', data + 'Какие утверждения верны? Выберите все верные.', ok, rng.sample(bad, 2), ['sql']),
                              make_brief(rng, 'multiple_choice', scenario, topic, restr))
    out['open_response'] = (open_task('Ловушка NOT IN с NULL', data + 'Объясните, сколько строк вернёт запрос с NOT IN и как исправить запрос, чтобы NULL не искажал результат.',
                                      'результат не определён либо NULL считается обычным значением',
                                      f'назван результат {not_in}, но нет причины или исправления',
                                      f'запрос вернёт {plural(not_in, 'строка', 'строки', 'строк')}, так как сравнение с NULL даёт неопределённость; исправление — WHERE y IS NOT NULL в подзапросе (результат {not_in_nonnull}) или NOT EXISTS',
                                      ['sql']), make_brief(rng, 'open_response', scenario, topic, restr))
    return {'spec': 'backend', 'skills': ['sql'], 'tasks': out}


FAMILIES = [sql_null_aggregates, sql_filter_count, sql_group_having, sql_join_counts, sql_dml_affected, sql_not_in_null]
