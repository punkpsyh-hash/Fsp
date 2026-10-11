"""Ограниченные задачи команды: валидация и покрытие формальных навыков."""
import pytest
from pydantic import ValidationError

from src.server.assessment import CATALOG
from src.server.schemas import NeedInput, ResumeInput, SearchInput
from src.server.skill_evidence import DECLARED_SKILLS
from src.server.work_requirements import WORK_TASKS_VERSION, catalog, desired_for_tasks, resolve, task_matches


def test_declared_taxonomy_is_bounded_deduplicated_and_keeps_multistack():
    resume = ResumeInput(declared_skills=['react', 'python', 'react', 'docker'])
    assert resume.declared_skills == ['react', 'python', 'docker']
    assert set(resume.declared_skills) <= {entry['id'] for entry in DECLARED_SKILLS}
    assert ResumeInput().declared_skills == []
    for skills in [['arbitrary text'], ['Python'], [True], ['python'] * 21]:
        with pytest.raises(ValidationError):
            ResumeInput(declared_skills=skills)


def test_work_catalog_is_versioned_specialization_scoped_and_independent():
    assert WORK_TASKS_VERSION == 'team-work-v1'
    all_tasks = catalog()
    assert len({task['id'] for task in all_tasks}) == len(all_tasks)
    for spec in CATALOG:
        tasks = catalog(spec)
        assert tasks
        for task in tasks:
            assert task['specialization'] == spec
            assert set(task['skills']) <= set(CATALOG[spec]['skills'])
            assert 'демо-проверка' in task['label'] and 'Ограниченная' in task['description']
    all_tasks[0]['skills'].append('react')
    assert 'react' not in catalog()[0]['skills']


def test_work_selection_preserves_hard_filter_and_desired_input():
    query = SearchInput(work_tasks=['api-development', 'sql-reporting', 'api-development'],
                        must_skills=['sql'], desired_skills=[])
    assert query.work_tasks == ['api-development', 'sql-reporting']
    assert query.must_skills == ['sql'] and query.desired_skills == []
    assert desired_for_tasks(query.work_tasks, 'backend') == ['python', 'http', 'sql']
    need = NeedInput(title='Тестовая команда', description='Синтетическая потребность команды в задачах API.', **query.model_dump())
    assert need.model_dump()['work_tasks'] == query.work_tasks
    assert resolve([]) == [] and SearchInput().work_tasks == []


@pytest.mark.parametrize('task_ids', [['not-a-task'], ['ui-accessibility'], ['api-development'] * 7, [True], ['']])
def test_search_rejects_unknown_foreign_or_oversized_work_selection(task_ids):
    with pytest.raises(ValidationError):
        SearchInput(work_tasks=task_ids)


def test_task_matches_exposes_per_task_gaps_without_inventing_experience():
    rows = task_matches(['python'], ['api-development', 'code-review', 'sql-reporting'])
    assert rows[0]['status'] == 'partial' and rows[0]['matched_skills'] == ['python']
    assert rows[0]['missing_skills'] == ['http']
    assert rows[1]['status'] == 'covered' and rows[1]['missing_skills'] == []
    assert rows[2]['status'] == 'gap' and rows[2]['missing_skills'] == ['sql']
    assert task_matches([], ['code-review'])[0]['status'] == 'gap'
    with pytest.raises(ValueError):
        desired_for_tasks(['api-testing'], 'backend')
