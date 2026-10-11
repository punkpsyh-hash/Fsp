"""Markdown renderer и совместимая manifest-based сборка документации.

Функция ``markdown`` остаётся общим renderer для письменного комплекта. Команда
собирает canonical ``docs/delivery/gost/documentation.pdf`` из источников, явно
перечисленных в ``docs/document-set.json``.
"""
import argparse
import json
from pathlib import Path

import yaml
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.platypus import PageBreak, Spacer

from gost_layout import (
    BLACK,
    CONTENT_WIDTH,
    FONT_BOLD,
    FONT_REGULAR,
    GostContext,
    LIGHT_GRAY,
    ROOT,
    STYLES,
    figures_appendix,
    gost_document,
    make_table,
    markdown as gost_markdown,
    page_number_after_title,
    para,
    table_flowables,
)

INK = BLUE = RED = GRAY = BLACK
WASH = LIGHT_GRAY


# ---------- схемы ----------
def _box(d, x, y, w, h, lines, fill=WASH, stroke=BLUE, size=12, bold_first=True):
    d.add(Rect(x, y, w, h, fillColor=fill, strokeColor=stroke, strokeWidth=0.8))
    top = y + h - 16
    for i, text in enumerate(lines):
        d.add(String(x + 6, top - i * 15, text, fontName=FONT_BOLD if i == 0 and bold_first else FONT_REGULAR,
                     fontSize=size,
                     fillColor=INK))


def _arrow(d, x1, y1, x2, y2):
    d.add(Line(x1, y1, x2, y2, strokeColor=RED, strokeWidth=0.9))
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 4.5
    d.add(Polygon([x2, y2, x2 - size * math.cos(angle - 0.4), y2 - size * math.sin(angle - 0.4),
                   x2 - size * math.cos(angle + 0.4), y2 - size * math.sin(angle + 0.4)], fillColor=RED, strokeColor=RED))


def diagram_components():
    d = Drawing(CONTENT_WIDTH, 420)
    left, middle, right = 0, 150, 346
    _box(d, left, 320, 126, 82, ['Браузер', 'React 19, TypeScript', 'Два кабинета', 'Мониторинг теста'])
    _box(d, middle, 210, 170, 192, ['API: FastAPI', 'Сессии и профили', 'Оценка теста', 'Подбор и объяснение',
                                  'Приглашения', 'Доступ к контакту', 'mock ФСП ID', 'OIDC + PKCE', 'ИИ-помощник'])
    _box(d, right, 320, 121, 82, ['База данных', 'PostgreSQL 16', 'SQLite', 'Alembic'])
    _box(d, right, 210, 121, 82, ['VM-раннер', 'Python, JS, SQL', 'Одноразовые VM', 'Без сети'])
    _box(d, right, 100, 121, 82, ['Почта', 'SMTP (TLS)', 'Или локальная', 'demo-почта'])
    _box(d, middle, 100, 170, 82, ['LLM-сервер', 'OpenAI-совместимый', 'Локальный или HTTPS', 'По умолчанию выключен'])
    _box(d, left, 210, 126, 82, ['Реестр ФСП', 'Сейчас: demo-реестр', 'План: клиент', 'ФСП ID'])
    _arrow(d, 126, 361, middle, 361)
    _arrow(d, 320, 361, right, 361)
    _arrow(d, 320, 300, right, 251)
    _arrow(d, 320, 270, right, 141)
    _arrow(d, 235, 210, 235, 182)
    _arrow(d, middle, 251, 126, 251)
    d.add(String(0, 62, 'Стрелки показывают направление вызова.', fontName=FONT_REGULAR, fontSize=12, fillColor=GRAY))
    d.add(String(0, 44, 'API не запускает пользовательский код.', fontName=FONT_REGULAR, fontSize=12, fillColor=GRAY))
    d.add(String(0, 26, 'Для запуска кода используется отдельный VM-раннер.', fontName=FONT_REGULAR, fontSize=12, fillColor=GRAY))
    return d


def diagram_contact():
    d = Drawing(CONTENT_WIDTH, 245)
    steps = [('Кандидат', 'Тест', 'Категория', 'Публикация'), ('Компания', 'Потребность', 'Подборка'),
             ('Приглашение', 'Зарплата', 'Компания', 'Связь'), ('Кандидат', 'Принять', 'Отклонить'),
             ('Контакт', 'Только этой', 'компании')]
    width, gap = 82, (CONTENT_WIDTH - 5 * 82) / 4
    for i, lines in enumerate(steps):
        x = i * (width + gap)
        _box(d, x, 135, width, 82, list(lines))
        if i < len(steps) - 1:
            _arrow(d, x + width, 176, x + width + gap, 176)
    for y, text in [(102, 'До принятия приглашения или отклика контакт скрыт'),
                    (84, 'в поиске, API и PDF. Самостоятельный отклик открывает контакт'),
                    (66, 'только компании — владельцу вакансии.')]:
        d.add(String(0, y, text, fontName=FONT_REGULAR, fontSize=12, fillColor=INK))
    return d


def diagram_assessment():
    d = Drawing(CONTENT_WIDTH, 365)
    top_y, box_w, gap = 250, 102, (CONTENT_WIDTH - 4 * 102) / 3
    top = [('Форма v6', '12 заданий', '3 навыка', 'Параметры seed'), ('Ответы', 'Сервер хранит', 'И считает время'),
           ('Балл и сигналы', 'Ключи на сервере', 'Поведение в тесте'), ('У порога ±6?', 'Нет: решение', 'Да: вторая форма')]
    xs = [i * (box_w + gap) for i in range(4)]
    for x, lines in zip(xs, top):
        _box(d, x, top_y, box_w, 82, list(lines))
    for i in range(3):
        _arrow(d, xs[i] + box_w, 291, xs[i + 1], 291)
    _box(d, 0, 120, 142, 100, ['Правила грейда', 'Повышение: 90 суток', 'Понижение: сразу', 'Повтор: 14 суток', 'История событий'])
    _box(d, 163, 120, 142, 100, ['Вторая форма', 'Новые задания', 'Без ожидания', 'Итог: среднее двух'])
    _box(d, 326, 120, 141, 100, ['Решение', 'Junior 70, Middle 80', 'Провал не понижает', 'При сигналах: повтор'])
    _arrow(d, xs[3] + box_w / 2, top_y, 234, 220)
    _arrow(d, 305, 170, 326, 170)
    d.add(String(0, 80, 'Пороги и полоса ±6 — решения команды.', fontName=FONT_REGULAR, fontSize=12, fillColor=GRAY))
    d.add(String(0, 62, 'Синтетические проверки описаны в docs/48.', fontName=FONT_REGULAR, fontSize=12, fillColor=GRAY))
    d.add(String(0, 44, 'но не калиброваны по людям.', fontName=FONT_REGULAR, fontSize=12, fillColor=GRAY))
    return d


DIAGRAMS = {
    'diagram_components': (diagram_components, 'Компоненты решения и направления вызовов'),
    'diagram_contact': (diagram_contact, 'Контур открытия контактных данных'),
    'diagram_assessment': (diagram_assessment, 'Порядок оценки и подтверждения уровня'),
}


def markdown(path, skip_first_h1=True, context=None):
    return gost_markdown(path, skip_first_h1=skip_first_h1, context=context, diagrams=DIAGRAMS)


def api_table(schema):
    rows = [['Метод', 'Путь', 'Назначение']]
    for path, methods in schema['paths'].items():
        for method, spec in methods.items():
            if method in {'get', 'post', 'put', 'patch', 'delete'}:
                rows.append([method.upper(), path, (spec.get('summary') or spec.get('operationId', '')).strip()[:110]])
    return rows


def versions_rows():
    rows = [['Компонент', 'Версия']]
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if '==' in line:
            name, version = line.split('==', 1)
            rows.append([name, version])
    package = json.loads((ROOT / 'web/package.json').read_text())
    for group in ('dependencies', 'devDependencies'):
        for name, version in package[group].items():
            rows.append([name + ' (web)', version])
    return rows


footer = page_number_after_title


def build(
    out: Path,
    manifest: Path = ROOT / "docs/document-set.json",
) -> None:
    """Собрать canonical documentation через общий manifest-based renderer."""
    from build_gost_documents import build_named

    build_named("documentation", out, manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs/delivery/gost/documentation.pdf",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "docs/document-set.json",
    )
    arguments = parser.parse_args()
    build(arguments.out, arguments.manifest)
