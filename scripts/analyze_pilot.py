"""Описательные результаты введённого пилота; пустой шаблон не является пилотом."""
import argparse
import csv
import json
import math
from pathlib import Path
import re

COLUMNS = ['participant_code', 'specialization', 'requested_grade', 'score',
           'expert_grade', 'parallel_score', 'minutes', 'form_version']


def number(value, name, low, high, optional=False):
    if optional and value == '':
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError('Некорректное поле '+name) from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError('Поле вне допустимых границ: '+name)
    return result


def analyze(rows):
    records, seen = [], set()
    for index, row in enumerate(rows, 2):
        if set(row) != set(COLUMNS):
            raise ValueError(f'Строка {index}: неверный набор полей')
        if not re.fullmatch(r'P[0-9]{3,6}', row['participant_code']):
            raise ValueError(f'Строка {index}: нужен обезличенный код P001')
        spec, grade = row['specialization'], row['requested_grade']
        if spec not in {'backend', 'frontend', 'qa'} or grade not in {'junior', 'middle'}:
            raise ValueError(f'Строка {index}: неподдерживаемая специализация/грейд')
        key = (row['participant_code'], spec, grade)
        if key in seen:
            raise ValueError(f'Строка {index}: повтор участника в одной группе')
        seen.add(key)
        if not re.fullmatch(r'[A-Za-z0-9.-]{1,50}', row['form_version']):
            raise ValueError(f'Строка {index}: некорректная версия формы')
        expert = row['expert_grade'] or None
        if expert not in {None, 'unconfirmed', 'junior', 'middle'}:
            raise ValueError(f'Строка {index}: неподдерживаемая экспертная категория')
        score = number(row['score'], 'score', 0, 100)
        records.append({'spec': spec, 'requested': grade, 'score': score,
                        'category': grade if score >= (70 if grade == 'junior' else 80) else 'unconfirmed',
                        'expert': expert, 'parallel': number(row['parallel_score'], 'parallel_score', 0, 100, True),
                        'minutes': number(row['minutes'], 'minutes', 0.01, 480, True),
                        'version': row['form_version']})
    groups = []
    for spec, grade in sorted({(r['spec'], r['requested']) for r in records}):
        group = [r for r in records if r['spec'] == spec and r['requested'] == grade]
        expert = [r for r in group if r['expert'] is not None]
        parallel = [r for r in group if r['parallel'] is not None]
        timed = [r['minutes'] for r in group if r['minutes'] is not None]
        confusion = {label: {other: 0 for other in ('unconfirmed', 'junior', 'middle')}
                     for label in ('unconfirmed', 'junior', 'middle')}
        for r in expert:
            confusion[r['expert']][r['category']] += 1
        groups.append({'specialization': spec, 'requested_grade': grade, 'observations': len(group),
                       'form_versions': sorted({r['version'] for r in group}),
                       'expert_observations': len(expert), 'missing_expert': len(group)-len(expert),
                       'category_agreement': sum(r['expert']==r['category'] for r in expert)/len(expert) if expert else None,
                       'confusion_expert_rows_test_columns': confusion,
                       'parallel_observations': len(parallel),
                       'mean_absolute_score_difference': sum(abs(r['score']-r['parallel']) for r in parallel)/len(parallel) if parallel else None,
                       'timed_observations': len(timed), 'mean_minutes': sum(timed)/len(timed) if timed else None})
    return {'status': 'observations-supplied' if records else 'not-conducted',
            'observations': len(records), 'groups': groups,
            'limitations': ['Независимость и происхождение введённых наблюдений скрипт не удостоверяет.',
                            'Показатели описательные: нет доказательства профессионального грейда, равной сложности или качества найма.',
                            'Число наблюдений не равно числу независимых людей между группами; пропуски показаны отдельно.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.input.open(newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != COLUMNS:
                raise ValueError('Заголовок CSV должен совпадать с шаблоном')
            report = analyze(list(reader))
    except (ValueError, OSError):
        parser.exit(2, 'Данные пилота не обработаны: проверьте поля, границы и формат шаблона. Содержимое строк не выводится.\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status': report['status'], 'observations': report['observations']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
