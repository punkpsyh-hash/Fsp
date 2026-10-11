"""Источник подтверждения: актуальный профиль, финальная практика и приватность."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from tests.test_api import client
from src.server.assessment import VERSION, evaluate, questions
from src.server.bank_models import BankAttempt, BankCodeJob, BankReview, BankVersion, TaskBank
from src.server.models import Attempt, Profile, TaskResponse, now
from src.server.skill_evidence import skill_evidence


@pytest.fixture
def db(client):
    with client.app.state.factory() as session:
        yield session


def confirmed(db, *, specialization='backend', grade='junior', at=None):
    profile = db.get(Profile, 'demo-candidate-a')
    at = at or now()
    form = questions(732, grade, specialization, VERSION)
    result = evaluate(732, grade, {q['id']: q['answer'] for q in form}, specialization, VERSION, form=form)
    profile.specialization, profile.confirmed_grade = specialization, grade
    profile.skills, profile.test_score, profile.assessed_at = result['skills'], result['score'], at
    attempt = Attempt(candidate_id=profile.user_id, grade=grade, specialization=specialization,
                      seed=732, created_at=at-timedelta(minutes=10), submitted_at=at+timedelta(microseconds=200),
                      blueprint_version=VERSION, score=result['score'], result=result, question_form=form,
                      answers={'private-answer': 'SECRET_CONTENT'})
    db.add(attempt)
    db.flush()
    return profile, attempt


def practice(db, profile, *, scope='platform', scores=(100, 0), skills=(['python'], ['sql']), status='completed'):
    bank = TaskBank(owner_id='demo-employer-x', external_id='test-'+str(now().timestamp()),
                    title='SECRET_BANK_NAME', scope=scope)
    db.add(bank)
    db.flush()
    tasks = [{'id': 'task-'+str(i), 'skills': skill, 'weight': i+1,
              'prompt': 'SECRET_PROMPT', 'answer_key': ['SECRET_KEY'], 'type': 'numeric'}
             for i, skill in enumerate(skills)]
    version = BankVersion(bank_id=bank.id, state='published',
                          document={'specialization': profile.specialization, 'tasks': tasks, 'title': 'SECRET_TITLE'})
    db.add(version)
    db.flush()
    result = {'score': round(sum(score*(i+1) for i, score in enumerate(scores))/sum(range(1, len(scores)+1)), 2),
              'completed': True, 'pending_count': 0,
              'tasks': [{'task_id': task['id'], 'score': score, 'status': 'scored', 'feedback': 'SECRET_FEEDBACK'}
                        for task, score in zip(tasks, scores)]}
    attempt = BankAttempt(candidate_id=profile.user_id, version_id=version.id, status=status,
                          result=result, submitted_at=now(), deadline=now()+timedelta(hours=1),
                          answers={'task-0': 'SECRET_SOURCE'})
    db.add(attempt)
    db.flush()
    return attempt, version


def test_seed_is_legacy_without_fabricated_per_skill_scores(db):
    profile = db.get(Profile, 'demo-candidate-a')
    evidence = skill_evidence(db, profile)
    assert [row['skill'] for row in evidence['assessment']] == profile.skills
    assert all(row['source'] == 'legacy-assessment' for row in evidence['assessment'])
    assert all(row['score'] is None and row['correct'] is None and row['total'] is None and row['version'] is None
               for row in evidence['assessment'])
    assert any('seed/legacy' in limit for limit in evidence['limitations'])


def test_current_assessment_snapshot_survives_later_failed_attempt(db):
    profile, passed = confirmed(db)
    db.add(Attempt(candidate_id=profile.user_id, grade='junior', specialization='backend', seed=24,
                   blueprint_version=VERSION, submitted_at=now()+timedelta(days=1), score=0,
                   result={'passed': False, 'score': 0, 'skills': [], 'breakdown': [], 'version': VERSION}))
    db.flush()
    evidence = skill_evidence(db, profile)
    assert len(evidence['assessment']) == 3
    assert all(row['source'] == 'assessment' and row['score'] == 100 for row in evidence['assessment'])
    assert all(row['version'] == VERSION for row in evidence['assessment'])
    assert profile.skills == passed.result['skills'] and profile.test_score == 100


def test_historical_other_grade_or_specialization_cannot_explain_current_profile(db):
    profile, _ = confirmed(db, at=now()-timedelta(days=1))
    profile.assessed_at = now()
    historical = skill_evidence(db, profile)
    assert all(row['source'] == 'legacy-assessment' for row in historical['assessment'])
    profile, attempt = confirmed(db)
    attempt.specialization = 'qa'
    db.flush()
    assert all(row['source'] == 'legacy-assessment' for row in skill_evidence(db, profile)['assessment'])
    attempt.specialization, attempt.grade = 'backend', 'middle'
    db.flush()
    assert all(row['source'] == 'legacy-assessment' for row in skill_evidence(db, profile)['assessment'])


def test_ambiguous_snapshot_cannot_supply_detailed_confirmation(db):
    profile, original = confirmed(db)
    db.add(Attempt(candidate_id=profile.user_id, grade=original.grade, specialization=original.specialization,
                   seed=original.seed, blueprint_version=original.blueprint_version, score=original.score,
                   result=deepcopy(original.result), submitted_at=original.submitted_at,
                   created_at=original.created_at))
    db.flush()
    assert all(row['source'] == 'legacy-assessment' for row in skill_evidence(db, profile)['assessment'])


def test_snapshot_requires_consistent_scores_skill_set_and_finite_breakdown(db):
    profile, attempt = confirmed(db)
    original = deepcopy(attempt.result)
    mutations = [lambda r: r.update(score=90), lambda r: r.update(skills=['python']),
                 lambda r: r['breakdown'][0].update(score=float('nan')),
                 lambda r: r['breakdown'][0].update(correct=999),
                 lambda r: r.update(version='SECRET_VERSION')]
    for mutate in mutations:
        result = deepcopy(original)
        mutate(result)
        attempt.result = result
        # PostgreSQL JSON rejects NaN on persistence; exercise defensive reading
        # with the malformed snapshot in memory without storing invalid JSON.
        with db.no_autoflush:
            assert all(row['source'] == 'legacy-assessment' for row in skill_evidence(db, profile)['assessment'])
    attempt.result = original


@pytest.mark.parametrize('status', ['in_progress', 'pending_review', 'expired'])
def test_partial_or_expired_practice_does_not_confirm_skills(db, status):
    profile, _ = confirmed(db)
    practice(db, profile, status=status)
    assert skill_evidence(db, profile)['practice'] == []


def test_completed_practice_keeps_sources_zero_scores_and_no_grade_effect(db):
    profile, _ = confirmed(db)
    original = (profile.confirmed_grade, deepcopy(profile.skills), profile.test_score)
    attempt, _ = practice(db, profile)
    practice(db, profile, scope='employer', scores=(50,), skills=(['python'],))
    finished_at = attempt.submitted_at+timedelta(minutes=15)
    db.add(BankReview(attempt_id=attempt.id, task_id='task-0', reviewer_id='demo-employer-x', score=100,
                      feedback='SECRET_REVIEW', created_at=finished_at))
    db.flush()
    rows = skill_evidence(db, profile)['practice']
    platform = {row['skill']: row for row in rows if row['source'] == 'platform-practice'}
    assert platform['python']['score'] == 100 and platform['python']['tasks'] == 1
    assert platform['sql']['score'] == 0 and platform['sql']['tasks'] == 0 and platform['sql']['total_tasks'] == 1
    assert platform['python']['completed_at'] == finished_at
    assert next(row for row in rows if row['source'] == 'employer-practice')['score'] == 50
    assert (profile.confirmed_grade, profile.skills, profile.test_score) == original


def test_practice_aggregation_uses_task_skill_and_weight_and_final_result(db):
    profile, _ = confirmed(db)
    attempt, _ = practice(db, profile, scores=(100, 0), skills=(['python'], ['python']))
    row = skill_evidence(db, profile)['practice'][0]
    assert row['score'] == 33.33 and row['tasks'] == 1 and row['total_tasks'] == 2
    original = deepcopy(attempt.result)
    for change in ({'completed': False}, {'pending_count': 1}, {'score': float('nan')}):
        attempt.result = original | change
        with db.no_autoflush:
            assert skill_evidence(db, profile)['practice'] == []
    attempt.result = deepcopy(original)
    attempt.result['tasks'][0]['score'] = None
    db.flush()
    assert skill_evidence(db, profile)['practice'] == []


def test_unmapped_general_score_and_unreviewed_job_cannot_invent_skill(db):
    profile, _ = confirmed(db)
    attempt, _ = practice(db, profile, scores=(100,), skills=([],))
    db.add(TaskResponse(task_id='demo-task-backend', candidate_id=profile.user_id,
                        answer='SECRET_RESPONSE', score=99, feedback='SECRET_RUBRIC', reviewed_at=now()))
    db.add(BankCodeJob(attempt_id=attempt.id, task_id='task-0', status='queued', source='SECRET_CODE', source_hash='0'*64))
    db.flush()
    evidence = skill_evidence(db, profile)
    assert evidence['practice'] == []
    assert any('без навыков' in limit for limit in evidence['limitations'])


def test_general_employer_review_explains_missing_skill_evidence(db):
    profile, _ = confirmed(db)
    db.add(TaskResponse(task_id='demo-task-backend', candidate_id=profile.user_id,
                        answer='Синтетический ответ на общую задачу.', score=100,
                        feedback='Синтетическая общая рубрика.', reviewed_at=now()))
    db.flush()
    evidence = skill_evidence(db, profile)
    assert evidence['practice'] == []
    assert any('без навыков' in limit for limit in evidence['limitations'])


def test_projection_drops_free_text_unknown_tags_answers_and_personal_data(db):
    profile, _ = confirmed(db)
    profile.resume = {'full_name': 'SECRET_PERSON', 'about': 'SECRET_ABOUT',
                      'declared_skills': ['python', 'react', 'python', 'SECRET_SKILL', {'bad': 'SECRET_DICT'}]}
    practice(db, profile)
    evidence = skill_evidence(db, profile)
    assert evidence['declared'] == ['python', 'react']
    assert set(evidence) == {'declared', 'assessment', 'practice', 'limitations'}
    assert 'SECRET' not in json.dumps(evidence, default=str)
    assert 'demo-employer' not in json.dumps(evidence, default=str)
    assert 'answers' not in json.dumps(evidence, default=str)


def test_no_confirmed_grade_does_not_promote_stale_skills_or_declarations(db):
    profile = db.get(Profile, 'demo-candidate-a')
    profile.confirmed_grade = None
    profile.resume = {'declared_skills': ['python', 'fastapi']}
    evidence = skill_evidence(db, profile)
    assert evidence['assessment'] == [] and evidence['declared'] == ['python', 'fastapi']
