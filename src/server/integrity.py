"""Сигналы добросовестности при тесте: переключения вкладок, копирование, темп ответов.

Принципы:
* это сигналы, а не доказательство: единичное переключение (уведомление, звонок)
  ничего не меняет; решают повторяющиеся признаки и их сочетания;
* темп ответов измеряется на сервере по времени сохранения черновиков и не
  зависит от клиента; события браузера присылает клиент, их можно подделать,
  поэтому «тишина» тоже сигнал (пульс monitoring_gap);
* собирается только тип события, время и номер вопроса. Текст вопросов и ответов,
  содержимое буфера, экран и камера не собираются;
* не блокирует ни кандидата, ни тест. Результат «flagged» у прошедшего тест
  удерживает подтверждение грейда до перепроверки на новой форме.
Не защищает от второго устройства и телефона: это ограничение описано в docs/28.
"""

ALLOWED_EVENTS = ('hidden', 'visible', 'blur', 'focus', 'copy', 'cut', 'paste', 'contextmenu',
                  'shortcut', 'fullscreen_exit', 'heartbeat', 'answer')
TIMELINE_CODES = {'hidden': 'h', 'visible': 'v', 'answer': 'a', 'copy': 'c', 'cut': 'c'}
HEARTBEAT_MS = 15_000
MAX_LOG = 160           # записей хронологии на попытку
MAX_AWAY_MS = 3_600_000
MAX_EVENTS_PER_ATTEMPT = 1_500

# (review, flagged): значение сигнала, начиная с которого сигнал меняет уровень.
THRESHOLDS = {
    'tab_leaves': (3, 8),             # число уходов со вкладки (visibilitychange)
    'away_seconds': (45, 240),        # суммарно вне вкладки
    'focus_losses': (6, 20),          # окно потеряло фокус без скрытия (соседнее окно)
    'clipboard_copies': (1, 4),       # копирование/вырезание текста вопроса
    'blocked_shortcuts': (4, 12),     # Ctrl+C/A/U/P/S, F12 и т.п.
    'answers_after_return': (4, 7),   # ответы в течение 25 с после возврата на вкладку
    'monitoring_gap_seconds': (150, 600),  # нет пульса клиента
    'event_budget_exceeded': (1, 1),      # переполнение не выключает последующие сигналы
}
FAST_MEDIAN_SECONDS = (12, 6)         # медиана секунд на вопрос: (review, flagged), меньше — сигнал
RETURN_WINDOW_MS = 25_000
MIN_ANSWERS_FOR_PACE = 6

MESSAGES = {
    'tab_leaves': 'Несколько раз покидали вкладку с тестом',
    'away_seconds': 'Долго находились вне вкладки с тестом',
    'focus_losses': 'Окно теста часто теряло фокус',
    'clipboard_copies': 'Копировали текст вопроса',
    'blocked_shortcuts': 'Использовали сочетания клавиш копирования/просмотра исходного кода',
    'answers_after_return': 'Ответы шли сразу после возвратов на вкладку',
    'monitoring_gap_seconds': 'Клиент теста долго не передавал сигналы',
    'bulk_answers': 'Ответы переданы одной пачкой, темп ответов не измерен',
    'median_seconds_per_answer': 'Слишком быстрые ответы на вопросы с чтением кода',
    'event_budget_exceeded': 'Превышено допустимое число событий попытки; нужна перепроверка',
}


def new_state():
    return {'v': 1, 'counts': {}, 'away_ms': 0, 'gap_ms': 0, 'last_beat': None, 'log': [],
            'answered': {}, 'events': 0}


def record_events(state, events, elapsed_seconds=None):
    """Добавляет события клиента (уже проверенные схемой) в состояние."""
    if elapsed_seconds is not None and any(event['type'] == 'heartbeat' for event in events):
        previous = state.get('server_last_beat', 0)
        gap = max(0, elapsed_seconds - previous - HEARTBEAT_MS / 1000)
        if gap > 3 * HEARTBEAT_MS / 1000:
            state['server_gap_seconds'] = min(state.get('server_gap_seconds', 0) + gap, MAX_AWAY_MS / 1000)
        state['server_last_beat'] = elapsed_seconds
    for event in events:
        kind, at = event['type'], event['t']
        state['events'] = min(state['events'] + 1, MAX_EVENTS_PER_ATTEMPT + 1)
        state['counts'][kind] = min(state['counts'].get(kind, 0) + 1, MAX_EVENTS_PER_ATTEMPT + 1)
        if kind == 'visible':
            state['away_ms'] = min(state['away_ms'] + (event.get('d') or 0), MAX_AWAY_MS)
        if kind == 'heartbeat':
            last = state['last_beat']
            if last is not None and at - last > 4 * HEARTBEAT_MS:
                state['gap_ms'] = min(state['gap_ms'] + at - last - HEARTBEAT_MS, MAX_AWAY_MS)
            state['last_beat'] = at
        code = TIMELINE_CODES.get(kind)
        if code and len(state['log']) < MAX_LOG:
            state['log'].append([at, code])
    return state


def note_answers(state, before, after, elapsed_seconds):
    """Фиксирует по часам сервера, когда ответ на вопрос появился или изменился."""
    for question, option in after.items():
        if before.get(question) != option and question not in state['answered']:
            state['answered'][question] = round(elapsed_seconds, 1)
    return state


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _answers_after_return(log):
    returns = [t for t, code in log if code == 'v']
    answers = [t for t, code in log if code == 'a']
    return sum(1 for a in answers if any(0 < a - r <= RETURN_WINDOW_MS for r in returns))


def assess(state, elapsed_seconds=None):
    """Возвращает уровень clean/review/flagged и список сработавших сигналов."""
    counts = state['counts']
    metrics = {
        'tab_leaves': counts.get('hidden', 0),
        'away_seconds': round(state['away_ms'] / 1000),
        'focus_losses': max(0, counts.get('blur', 0) - counts.get('hidden', 0)),
        'clipboard_copies': counts.get('copy', 0) + counts.get('cut', 0),
        'blocked_shortcuts': counts.get('shortcut', 0),
        'answers_after_return': _answers_after_return(state['log']),
        'monitoring_gap_seconds': round(state['gap_ms'] / 1000),
        'event_budget_exceeded': int(state['events'] > MAX_EVENTS_PER_ATTEMPT),
    }
    if elapsed_seconds is not None:
        last = state.get('server_last_beat')
        trailing = elapsed_seconds if last is None else max(0, elapsed_seconds - last - HEARTBEAT_MS / 1000)
        metrics['monitoring_gap_seconds'] = round(max(metrics['monitoring_gap_seconds'],
                                                     state.get('server_gap_seconds', 0) + trailing))
    signals = []
    for code, (review, flagged) in THRESHOLDS.items():
        value = metrics[code]
        if value >= flagged:
            signals.append({'code': code, 'level': 'flagged', 'value': value, 'message': MESSAGES[code]})
        elif value >= review:
            signals.append({'code': code, 'level': 'review', 'value': value, 'message': MESSAGES[code]})
    times = sorted(state['answered'].values())
    if len(times) >= MIN_ANSWERS_FOR_PACE:
        batched = len(times) - len(set(times))
        if batched >= len(times) / 2:
            # Ответы пришли одной пачкой (нет сохранений между вопросами): темп по ним не измерить.
            metrics['bulk_answers'] = batched
            # Долгая пачка возможна после сбоя сети. Мгновенная пачка не должна
            # обходить серверный порог скорости: длительность берётся с сервера.
            duration = elapsed_seconds if elapsed_seconds is not None else times[-1]
            level = 'flagged' if duration / len(times) < FAST_MEDIAN_SECONDS[1] else 'review'
            signals.append({'code': 'bulk_answers', 'level': level, 'value': batched,
                            'message': MESSAGES['bulk_answers']})
        else:
            gaps = [b - a for a, b in zip([0.0] + times, times)]
            median = _median(gaps)
            metrics['median_seconds_per_answer'] = round(median, 1)
            review, flagged = FAST_MEDIAN_SECONDS
            if median < review:
                level = 'flagged' if median < flagged else 'review'
                signals.append({'code': 'median_seconds_per_answer', 'level': level, 'value': round(median, 1),
                                'message': MESSAGES['median_seconds_per_answer']})
    level = 'flagged' if any(s['level'] == 'flagged' for s in signals) else 'review' if signals else 'clean'
    return {'level': level, 'signals': signals, 'metrics': metrics}
