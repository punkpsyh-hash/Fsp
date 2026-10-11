"""Конструктор, версии, безопасный импорт и выполнение наборов локального API."""
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
import math
import os
import secrets
from pathlib import PurePosixPath
from uuid import uuid4
from collections import defaultdict, deque
from threading import Lock, BoundedSemaphore
from time import monotonic
from zipfile import ZipFile, ZIP_DEFLATED
from fastapi import Depends, Header, HTTPException, Query, Request, Response
from anyio import CancelScope
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from pydantic import Field, StrictInt
from .models import User, now
from .bank_models import TaskBank, BankVersion, BankImport, BankAttempt, BankCodeJob, BankReview
from . import bank_schemas as S
from .bank_imports import MAX_UPLOAD, parse_import, csv_export, bounded_json
from .bank_review_ai import ReviewSuggestion, ReviewSuggestionInput, suggest_review
from .bank_generation import GenerationRequest, GenerationResult, GenerationUnavailable, GenerationRejected, generate_task


class TaskSuggestionInput(GenerationRequest):
    revision: StrictInt = Field(ge=1)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return sha256(raw).hexdigest()


def version_view(db, version, author=False):
    bank = db.get(TaskBank, version.bank_id)
    document = version.document
    return {'id': version.id, 'bank_id': bank.id, 'number': version.number, 'revision': version.revision,
            'state': version.state, 'scope': bank.scope, 'company_label': db.get(User, bank.owner_id).label,
            'title': document['title'], 'specialization': document['specialization'], 'grade': document['grade'],
            'time_limit_minutes': document['time_limit_minutes'], 'created_at': version.created_at,
            'published_at': version.published_at, 'tasks': document['tasks'] if author else [S.candidate_task(task) for task in document['tasks']],
            'validation_errors': S.publication_errors(document) if author else []}


def bank_view(db, bank):
    versions = list(db.scalars(select(BankVersion).where(BankVersion.bank_id == bank.id).order_by(BankVersion.number.desc())))
    return {'id': bank.id, 'title': bank.title, 'external_id': bank.external_id, 'scope': bank.scope,
            'created_at': bank.created_at, 'current_version': version_view(db, versions[0], True) if versions else None,
            'versions': [version_view(db, version, True) for version in versions]}


def attempt_view(db, attempt, author=False):
    version = db.get(BankVersion, attempt.version_id)
    return {'id': attempt.id, 'version_id': version.id, 'revision': attempt.revision, 'status': attempt.status,
            'deadline': attempt.deadline, 'created_at': attempt.created_at, 'submitted_at': attempt.submitted_at,
            'version': version_view(db, version, author), 'answers': attempt.answers, 'result': attempt.result,
            'candidate_alias': 'P-'+sha256(attempt.candidate_id.encode()).hexdigest()[:8].upper()}


def job_view(job):
    return {'id': job.id, 'task_id': job.task_id, 'status': job.status, 'execution_status': (job.result or {}).get('status'),
            'result': job.result, 'error_code': job.error_code, 'created_at': job.created_at, 'finished_at': job.finished_at}


def score_attempt(db, attempt):
    version = db.get(BankVersion, attempt.version_id)
    bank = db.get(TaskBank, version.bank_id)
    answers = attempt.answers
    rows = []
    for task in version.document['tasks']:
        value = answers.get(task['id'])
        score, status, feedback = 0.0, 'scored', None
        kind = task['type']
        if value is None or value == '' or value == []:
            feedback = 'Ответ не предоставлен'
        elif kind == 'single_choice': score = 100.0 if value == task['answer_key'][0] else 0.0
        elif kind == 'multiple_choice':
            selected, expected = set(value), set(task['answer_key'])
            if task['partial_credit']:
                score = max(0.0, (len(selected & expected)-len(selected-expected))/len(expected))*100
            else: score = 100.0 if selected == expected else 0.0
        elif kind == 'numeric':
            text = str(value).strip().replace(',', '.')
            if task['unit'] and text.endswith(task['unit']): text = text[:-len(task['unit'])].strip()
            tolerance = max(task['absolute_tolerance'], abs(task['numeric_answer'])*task['relative_tolerance'])
            score = 100.0 if math.isclose(float(text), task['numeric_answer'], rel_tol=0, abs_tol=tolerance) else 0.0
        elif kind == 'open_response':
            review = db.scalar(select(BankReview).where(BankReview.attempt_id == attempt.id, BankReview.task_id == task['id']))
            if review: score, feedback = float(review.score), review.feedback
            else: score, status = None, 'pending_review'
        elif kind == 'code':
            job = db.scalar(select(BankCodeJob).where(BankCodeJob.attempt_id == attempt.id, BankCodeJob.task_id == task['id'],
                         BankCodeJob.source_hash == sha256(value.encode()).hexdigest()).order_by(BankCodeJob.created_at.desc()))
            if job and job.result:
                if job.result['status'] == 'system_error': score, status, feedback = None, 'pending_code', 'Среда исполнения временно недоступна'
                else: score = float(job.result['score'])
            else: score, status = None, 'pending_code'
        rows.append({'task_id': task['id'], 'type': kind, 'score': score, 'status': status, 'feedback': feedback})
    pending = sum(row['score'] is None for row in rows)
    weight = sum(task['weight'] for task in version.document['tasks'])
    total = sum((row['score'] or 0)*task['weight'] for row, task in zip(rows, version.document['tasks']))/weight
    attempt.result = {'score': round(total, 2), 'pending_count': pending, 'completed': pending == 0,
                      'tasks': rows, 'scope': bank.scope, 'grade_effect': False, 'scorer_version': 'bank-v1'}
    attempt.status = 'pending_review' if pending else 'completed'
    # Практика работодателя, включая ручную оценку, никогда не меняет Profile/ConfirmedTrack.


def install_banks(app, db_session, employer, candidate, audit, aware):
    suggestion_calls, suggestion_lock = defaultdict(deque), Lock()
    suggestion_slots = BoundedSemaphore(2)
    import_calls, import_lock = {}, Lock()
    import_slots = BoundedSemaphore(2)

    def parse_admitted_import(raw, filename, mapping):
        # Освобождает worker, а не отменённый HTTP-запрос: разбор ещё может работать.
        try:
            return parse_import(raw, filename, mapping)
        finally:
            import_slots.release()

    def owned_bank(db, bank_id, user, lock=False):
        query = select(TaskBank).where(TaskBank.id == bank_id, TaskBank.owner_id == user.id)
        bank = db.scalar(query.with_for_update() if lock else query)
        if not bank: raise HTTPException(404, 'Набор не найден')
        return bank

    def owned_version(db, bank_id, version_id, user, lock=False):
        bank = owned_bank(db, bank_id, user, lock)
        version = db.scalar(select(BankVersion).where(BankVersion.id == version_id, BankVersion.bank_id == bank.id))
        if not version: raise HTTPException(404, 'Версия не найдена')
        return bank, version

    def own_attempt(db, attempt_id, user, lock=False):
        query = select(BankAttempt).where(BankAttempt.id == attempt_id, BankAttempt.candidate_id == user.id)
        attempt = db.scalar(query.with_for_update() if lock else query)
        if not attempt: raise HTTPException(404, 'Попытка не найдена')
        return attempt

    def active(attempt):
        if attempt.status != 'in_progress': raise HTTPException(409, 'Попытка уже отправлена')
        if aware(attempt.deadline) <= now(): raise HTTPException(409, 'Время попытки истекло; можно отправить сохранённые ответы')

    def require_scope(user, scope):
        if scope == 'platform' and not (user.id == 'demo-employer-x' and user.demo_seed):
            raise HTTPException(403, 'Платформенный банк доступен только локальному демо-куратору')

    def create_version(db, bank, document):
        versions = list(db.scalars(select(BankVersion).where(BankVersion.bank_id == bank.id)))
        number = max((version.number for version in versions), default=0)+1
        version = BankVersion(bank_id=bank.id, number=number, document=document)
        db.add(version)
        try: db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, 'Версия создана параллельно; загрузите актуальный набор')
        return version

    @app.get('/api/v1/company/banks', tags=['Конструктор'], response_model=list[S.BankView])
    def bank_list(user=Depends(employer), db=Depends(db_session)):
        return [bank_view(db, bank) for bank in db.scalars(select(TaskBank).where(TaskBank.owner_id == user.id).order_by(TaskBank.created_at.desc()))]

    @app.post('/api/v1/company/banks', status_code=201, tags=['Конструктор'], response_model=S.BankView)
    def bank_create(body: S.BankCreate, user=Depends(employer), db=Depends(db_session)):
        require_scope(user, body.scope)
        external = body.external_id or 'bank-'+uuid4().hex
        if db.scalar(select(TaskBank).where(TaskBank.owner_id == user.id, TaskBank.external_id == external)):
            raise HTTPException(409, 'Банк с таким external_id уже существует')
        bank = TaskBank(owner_id=user.id, external_id=external, title=body.title, scope=body.scope)
        db.add(bank)
        try: db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, 'Банк с таким external_id создан параллельно')
        create_version(db, bank, body.model_dump(exclude={'external_id', 'scope'}, mode='json'))
        audit(db, user, 'bank.created', bank.id); db.commit()
        return bank_view(db, bank)

    @app.get('/api/v1/company/banks/{bank_id}', tags=['Конструктор'], response_model=S.BankView)
    def bank_detail(bank_id: str, user=Depends(employer), db=Depends(db_session)):
        return bank_view(db, owned_bank(db, bank_id, user))

    @app.patch('/api/v1/company/banks/{bank_id}/versions/{version_id}', tags=['Конструктор'], response_model=S.VersionAuthor)
    def bank_save(bank_id: str, version_id: str, body: S.VersionSave, user=Depends(employer), db=Depends(db_session)):
        bank, version = owned_version(db, bank_id, version_id, user)
        document = body.model_dump(exclude={'revision'}, mode='json')
        result = db.execute(update(BankVersion).where(BankVersion.id == version.id, BankVersion.revision == body.revision,
                            BankVersion.state == 'draft').values(document=document, revision=BankVersion.revision+1))
        if result.rowcount != 1: raise HTTPException(409, 'Версия изменена в другой вкладке либо уже опубликована; загрузите актуальную версию')
        bank.title = body.title
        audit(db, user, 'bank.saved', version.id); db.commit(); db.refresh(version)
        return version_view(db, version, True)

    @app.post('/api/v1/company/banks/{bank_id}/versions/{version_id}/suggest-task', tags=['Конструктор'], response_model=GenerationResult)
    def bank_suggest_task(bank_id: str, version_id: str, body: TaskSuggestionInput,
                          user=Depends(employer), db=Depends(db_session)):
        _, version = owned_version(db, bank_id, version_id, user)
        if (version.state != 'draft' or version.revision != body.revision
                or body.specialization != version.document['specialization']
                or body.grade != version.document['grade']):
            raise HTTPException(409, 'Версия или параметры набора изменились; сохраните актуальный черновик')
        if not app.state.llm.enabled:
            raise HTTPException(503, 'ИИ-генерация выключена. Создайте задание вручную или подключите модель')
        if not suggestion_slots.acquire(blocking=False):
            raise HTTPException(503, 'Модель занята; повторите запрос позже', headers={'Retry-After': '5'})
        try:
            with suggestion_lock:
                calls = suggestion_calls[user.id]
                current_time = monotonic()
                while calls and current_time - calls[0] >= 60:
                    calls.popleft()
                if len(calls) >= 10:
                    raise HTTPException(429, 'Лимит генерации: 10 запросов в минуту', headers={'Retry-After': '60'})
                calls.append(current_time)
            request = GenerationRequest.model_validate(body.model_dump(exclude={'revision'}))
            try:
                result = generate_task(request, app.state.llm)
            except GenerationUnavailable:
                raise HTTPException(503, 'Модель недоступна. Черновик набора сохранён; попробуйте позже')
            except GenerationRejected:
                raise HTTPException(502, 'Ответ модели не прошёл проверку задания. Создайте задание вручную или повторите запрос')
            db.expire_all()
            _, latest = owned_version(db, bank_id, version_id, user)
            if latest.state != 'draft' or latest.revision != body.revision:
                raise HTTPException(409, 'Набор изменился во время генерации; предложение не добавлено')
            audit(db, user, 'bank.suggestion:' + result.source, version_id)
            db.commit()
            return result
        finally:
            suggestion_slots.release()

    @app.post('/api/v1/company/banks/{bank_id}/versions/{version_id}/publish', tags=['Конструктор'], response_model=S.VersionAuthor)
    def bank_publish(bank_id: str, version_id: str, body: S.Revision, user=Depends(employer), db=Depends(db_session)):
        _, version = owned_version(db, bank_id, version_id, user, True)
        if version.state != 'draft' or version.revision != body.revision: raise HTTPException(409, 'Версия уже изменена или опубликована')
        errors = S.publication_errors(version.document)
        if errors: raise HTTPException(422, 'Публикация запрещена: '+'; '.join(error['path']+': '+error['message'] for error in errors))
        result = db.execute(update(BankVersion).where(BankVersion.id == version.id, BankVersion.revision == body.revision,
            BankVersion.state == 'draft').values(state='published', revision=BankVersion.revision+1, published_at=now(), content_hash=digest(version.document)))
        if result.rowcount != 1: raise HTTPException(409, 'Версия изменена параллельно')
        audit(db, user, 'bank.published', version.id); db.commit(); db.refresh(version)
        return version_view(db, version, True)

    @app.post('/api/v1/company/banks/{bank_id}/versions/{version_id}/fork', status_code=201, tags=['Конструктор'], response_model=S.VersionAuthor)
    def bank_fork(bank_id: str, version_id: str, user=Depends(employer), db=Depends(db_session)):
        bank, source = owned_version(db, bank_id, version_id, user, True)
        version = create_version(db, bank, json.loads(json.dumps(source.document)))
        audit(db, user, 'bank.forked', version.id); db.commit()
        return version_view(db, version, True)

    @app.post('/api/v1/company/banks/{bank_id}/versions/{version_id}/archive', tags=['Конструктор'], response_model=S.VersionAuthor)
    def bank_archive(bank_id: str, version_id: str, user=Depends(employer), db=Depends(db_session)):
        _, version = owned_version(db, bank_id, version_id, user, True)
        if version.state == 'draft': raise HTTPException(409, 'Архивируются только опубликованные версии')
        version.state = 'archived'; version.revision += 1
        audit(db, user, 'bank.archived', version.id); db.commit()
        return version_view(db, version, True)

    @app.get('/api/v1/company/banks/{bank_id}/versions/{version_id}/preview', tags=['Конструктор'], response_model=S.VersionPublic)
    def bank_preview(bank_id: str, version_id: str, user=Depends(employer), db=Depends(db_session)):
        _, version = owned_version(db, bank_id, version_id, user)
        return version_view(db, version)

    @app.get('/api/v1/company/banks/{bank_id}/export', tags=['Импорт заданий'], response_model=S.BankDocument,
             responses={200: {'content': {'text/csv': {'schema': {'type': 'string'}}, 'application/zip': {'schema': {'type': 'string', 'format': 'binary'}}}}})
    def bank_export(bank_id: str, format: str = Query('json', pattern='^(json|csv|zip)$'), user=Depends(employer), db=Depends(db_session)):
        bank = owned_bank(db, bank_id, user)
        version = db.scalar(select(BankVersion).where(BankVersion.bank_id == bank.id).order_by(BankVersion.number.desc()))
        document = {'schema_version': 'fsp-bank-v1', 'external_id': bank.external_id, 'scope': bank.scope, **version.document}
        if format == 'zip':
            buffer = BytesIO()
            with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(document, ensure_ascii=False, indent=2))
            return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="bank.zip"'})
        if format == 'csv':
            try: content = csv_export(document)
            except ValueError as error: raise HTTPException(422, str(error))
            return Response(content, media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="bank.csv"'})
        return document

    @app.post('/api/v1/company/bank-imports/dry-run', tags=['Импорт заданий'], response_model=S.ImportView,
              responses={413: {'description': 'Файл превышает 2 МБ'},
                         429: {'description': 'Разбор занят или превышен лимит новых импортов'}})
    async def bank_import_preview(request: Request, filename: str = Query(max_length=200),
                                  column_mapping: str | None = Query(default=None, max_length=4000),
                                  user=Depends(employer), db=Depends(db_session)):
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_UPLOAD: raise HTTPException(413, 'Файл превышает 2 МБ')
        try: mapping = bounded_json(column_mapping) if column_mapping else None
        except (ValueError, RecursionError): raise HTTPException(422, 'Неверный JSON сопоставления колонок')
        if mapping is not None and not isinstance(mapping, dict): raise HTTPException(422, 'Сопоставление колонок должно быть объектом')
        content_hash = digest({'file_hash': digest(bytes(raw)), 'format': PurePosixPath(filename.lower()).suffix, 'columns': mapping})
        batch = db.scalar(select(BankImport).where(BankImport.owner_id == user.id, BankImport.content_hash == content_hash))
        if not batch:
            if not import_slots.acquire(blocking=False):
                raise HTTPException(429, 'Разбор импортов занят. Повторите позже', headers={'Retry-After': '60'})
            with import_lock:
                current = monotonic()
                # ponytail: максимум 1024 активных владельца, без вытеснения их лимитов.
                for owner, calls in list(import_calls.items()):
                    if calls[-1] <= current - 60:
                        del import_calls[owner]
                calls = import_calls.get(user.id)
                if calls is not None:
                    while calls and calls[0] <= current - 60:
                        calls.popleft()
                if (calls is not None and len(calls) >= 10) or (calls is None and len(import_calls) >= 1024):
                    import_slots.release()
                    raise HTTPException(429, 'Лимит новых импортов: 10 в минуту', headers={'Retry-After': '60'})
                if calls is None:
                    calls = import_calls[user.id] = deque()
                calls.append(current)
            # AnyIO отмена не прерывает ожидание worker; DB-сессия сохраняется до его окончания.
            with CancelScope(shield=True):
                document, errors, warnings = await run_in_threadpool(parse_admitted_import, bytes(raw), filename, mapping)
            if document: require_scope(user, document['scope'])
            batch = BankImport(owner_id=user.id, content_hash=content_hash, filename=filename,
                               document=document, errors=errors, warnings=warnings)
            db.add(batch)
            try: db.commit()
            except IntegrityError:
                db.rollback()
                batch = db.scalar(select(BankImport).where(BankImport.owner_id == user.id, BankImport.content_hash == content_hash))
        duplicate = db.scalar(select(TaskBank).where(TaskBank.owner_id == user.id, TaskBank.external_id == batch.document['external_id'])) if batch.document else None
        return {'id': batch.id, 'valid': not batch.errors, 'errors': batch.errors, 'warnings': batch.warnings,
                'preview': batch.document, 'duplicate_bank_id': duplicate.id if duplicate else None,
                'publication_errors': S.publication_errors(batch.document) if batch.document else []}

    @app.post('/api/v1/company/bank-imports/{import_id}/confirm', tags=['Импорт заданий'], response_model=S.BankView)
    def bank_import_confirm(import_id: str, user=Depends(employer), db=Depends(db_session)):
        batch = db.scalar(select(BankImport).where(BankImport.id == import_id, BankImport.owner_id == user.id).with_for_update())
        if not batch: raise HTTPException(404, 'Импорт не найден')
        if batch.errors or not batch.document: raise HTTPException(422, 'Исправьте ошибки импорта')
        if batch.bank_id: return bank_view(db, db.get(TaskBank, batch.bank_id))
        document = batch.document; require_scope(user, document['scope'])
        bank = db.scalar(select(TaskBank).where(TaskBank.owner_id == user.id, TaskBank.external_id == document['external_id']).with_for_update())
        if bank and bank.scope != document['scope']: raise HTTPException(409, 'Область существующего банка не совпадает')
        if not bank:
            bank = TaskBank(owner_id=user.id, external_id=document['external_id'], title=document['title'], scope=document['scope'])
            db.add(bank)
            try: db.flush()
            except IntegrityError:
                db.rollback(); raise HTTPException(409, 'Набор импортирован параллельно; повторите подтверждение')
        bank.title = document['title']
        create_version(db, bank, {key: document[key] for key in ['title', 'specialization', 'grade', 'time_limit_minutes', 'tasks']})
        batch.bank_id = bank.id; audit(db, user, 'bank.imported', bank.id); db.commit()
        return bank_view(db, bank)

    @app.get('/api/v1/candidate/banks', tags=['Выполнение заданий'], response_model=list[S.VersionPublic])
    def candidate_banks(user=Depends(candidate), db=Depends(db_session)):
        versions = list(db.scalars(select(BankVersion).where(BankVersion.state == 'published').order_by(BankVersion.published_at.desc())))
        # Показываем последнюю опубликованную версию каждого банка; история попыток остаётся.
        seen = set(); output = []
        for version in versions:
            if version.bank_id not in seen:
                seen.add(version.bank_id); output.append(version_view(db, version))
        return output

    @app.get('/api/v1/candidate/bank-attempts', tags=['Выполнение заданий'], response_model=list[S.AttemptPublic])
    def candidate_bank_history(user=Depends(candidate), db=Depends(db_session)):
        return [attempt_view(db, attempt) for attempt in db.scalars(select(BankAttempt).where(BankAttempt.candidate_id == user.id).order_by(BankAttempt.created_at.desc()))]

    @app.post('/api/v1/candidate/banks/{bank_id}/attempts', status_code=201, tags=['Выполнение заданий'], response_model=S.AttemptPublic)
    def bank_attempt_start(bank_id: str, body: S.AttemptStart, user=Depends(candidate), db=Depends(db_session)):
        version = db.get(BankVersion, body.version_id)
        if not version or version.bank_id != bank_id or version.state != 'published': raise HTTPException(404, 'Опубликованная версия не найдена')
        attempt = db.scalar(select(BankAttempt).where(BankAttempt.candidate_id == user.id, BankAttempt.version_id == version.id))
        if not attempt:
            attempt = BankAttempt(candidate_id=user.id, version_id=version.id, deadline=now()+timedelta(minutes=version.document['time_limit_minutes']))
            db.add(attempt)
            try: db.commit()
            except IntegrityError:
                db.rollback(); attempt = db.scalar(select(BankAttempt).where(BankAttempt.candidate_id == user.id, BankAttempt.version_id == version.id))
        return attempt_view(db, attempt)

    @app.get('/api/v1/candidate/bank-attempts/{attempt_id}', tags=['Выполнение заданий'], response_model=S.AttemptPublic)
    def bank_attempt_detail(attempt_id: str, user=Depends(candidate), db=Depends(db_session)):
        return attempt_view(db, own_attempt(db, attempt_id, user))

    @app.patch('/api/v1/candidate/bank-attempts/{attempt_id}', tags=['Выполнение заданий'], response_model=S.AttemptPublic)
    def bank_attempt_save(attempt_id: str, body: S.AnswersSave, user=Depends(candidate), db=Depends(db_session)):
        attempt = own_attempt(db, attempt_id, user); active(attempt)
        try: S.validate_answers(db.get(BankVersion, attempt.version_id).document, body.answers)
        except ValueError as error: raise HTTPException(422, str(error))
        result = db.execute(update(BankAttempt).where(BankAttempt.id == attempt.id, BankAttempt.revision == body.revision,
             BankAttempt.status == 'in_progress').values(answers=body.answers, revision=BankAttempt.revision+1))
        if result.rowcount != 1: raise HTTPException(409, 'Ответы изменены в другой вкладке; загрузите сохранённую попытку')
        db.commit(); db.refresh(attempt)
        return attempt_view(db, attempt)

    @app.post('/api/v1/candidate/bank-attempts/{attempt_id}/submit', tags=['Выполнение заданий'], response_model=S.AttemptPublic)
    def bank_attempt_submit(attempt_id: str, body: S.Revision, user=Depends(candidate), db=Depends(db_session)):
        attempt = own_attempt(db, attempt_id, user, True)
        if attempt.status != 'in_progress': return attempt_view(db, attempt)
        if attempt.revision != body.revision: raise HTTPException(409, 'Сохраните текущие ответы перед отправкой')
        changed = db.execute(update(BankAttempt).where(BankAttempt.id == attempt.id, BankAttempt.revision == body.revision,
                         BankAttempt.status == 'in_progress').values(status='submitting', revision=BankAttempt.revision+1))
        if changed.rowcount != 1: raise HTTPException(409, 'Попытка изменена параллельно; загрузите результат')
        db.refresh(attempt)
        # Отправка после deadline оценивает лишь ранее сохранённые ответы.
        version = db.get(BankVersion, attempt.version_id)
        for task in version.document['tasks']:
            source = attempt.answers.get(task['id'])
            if task['type'] == 'code' and source:
                source_hash = sha256(source.encode()).hexdigest()
                existing = db.scalar(select(BankCodeJob).where(BankCodeJob.attempt_id == attempt.id,
                       BankCodeJob.task_id == task['id'], BankCodeJob.source_hash == source_hash))
                if not existing: db.add(BankCodeJob(attempt_id=attempt.id, task_id=task['id'], source=source, source_hash=source_hash))
        attempt.submitted_at = now(); db.flush(); score_attempt(db, attempt)
        audit(db, user, 'bank.submitted', attempt.id); db.commit()
        return attempt_view(db, attempt)

    @app.post('/api/v1/candidate/bank-attempts/{attempt_id}/code-jobs', status_code=201, tags=['Выполнение кода'], response_model=S.CodeJobView)
    def bank_code_submit(attempt_id: str, body: S.CodeSubmit, user=Depends(candidate), db=Depends(db_session)):
        attempt = own_attempt(db, attempt_id, user, True)
        if attempt.status == 'in_progress': active(attempt)
        elif attempt.answers.get(body.task_id) != body.source:
            raise HTTPException(409, 'После отправки возможен только повтор исполнения сохранённого кода')
        task = next((task for task in db.get(BankVersion, attempt.version_id).document['tasks'] if task['id'] == body.task_id and task['type'] == 'code'), None)
        if not task: raise HTTPException(404, 'Задание кода не найдено')
        if not os.environ.get('FSP_RUNNER_TOKEN'): raise HTTPException(503, 'Изолированный runner не настроен')
        source_hash = sha256(body.source.encode()).hexdigest()
        previous = db.scalar(select(BankCodeJob).where(BankCodeJob.attempt_id == attempt.id, BankCodeJob.task_id == body.task_id,
                            BankCodeJob.source_hash == source_hash).order_by(BankCodeJob.created_at.desc()))
        if previous and previous.status != 'failed': return job_view(previous)
        jobs = list(db.scalars(select(BankCodeJob).where(BankCodeJob.attempt_id == attempt.id)))
        # 10 интерактивных проверок + резерв максимум 10 финальных задач: всего 20 jobs.
        budget = 10 if attempt.status == 'in_progress' else 20
        if len(jobs) >= budget: raise HTTPException(429, 'Лимит запусков: 10 предварительных и не более 20 суммарно с финальной отправкой')
        if any(job.status in {'queued', 'running'} for job in jobs): raise HTTPException(409, 'Дождитесь окончания предыдущего запуска')
        job = BankCodeJob(attempt_id=attempt.id, task_id=body.task_id, source=body.source, source_hash=source_hash)
        db.add(job); db.commit(); return job_view(job)

    @app.get('/api/v1/candidate/bank-attempts/{attempt_id}/code-jobs/{job_id}', tags=['Выполнение кода'], response_model=S.CodeJobView)
    def bank_code_detail(attempt_id: str, job_id: str, user=Depends(candidate), db=Depends(db_session)):
        own_attempt(db, attempt_id, user)
        job = db.get(BankCodeJob, job_id)
        if not job or job.attempt_id != attempt_id: raise HTTPException(404, 'Запуск не найден')
        return job_view(job)

    @app.get('/api/v1/company/banks/{bank_id}/attempts', tags=['Ручная проверка'], response_model=list[S.AttemptAuthor])
    def bank_reviews(bank_id: str, user=Depends(employer), db=Depends(db_session)):
        owned_bank(db, bank_id, user)
        query = select(BankAttempt).join(BankVersion, BankAttempt.version_id == BankVersion.id).where(BankVersion.bank_id == bank_id, BankAttempt.status != 'in_progress')
        return [attempt_view(db, attempt, True) for attempt in db.scalars(query.order_by(BankAttempt.submitted_at.desc()))]

    @app.post('/api/v1/company/bank-attempts/{attempt_id}/review-suggestion', tags=['Ручная проверка'], response_model=ReviewSuggestion)
    def bank_review_suggestion(attempt_id: str, body: ReviewSuggestionInput, user=Depends(employer), db=Depends(db_session)):
        attempt = db.scalar(select(BankAttempt).where(BankAttempt.id == attempt_id))
        if not attempt: raise HTTPException(404, 'Попытка не найдена')
        version = db.get(BankVersion, attempt.version_id); owned_bank(db, version.bank_id, user)
        if attempt.status == 'in_progress': raise HTTPException(409, 'Ответ ещё не отправлен')
        task = next((task for task in version.document['tasks'] if task['id'] == body.task_id and task['type'] == 'open_response'), None)
        if not task: raise HTTPException(422, 'Подсказка доступна только для открытого ответа')
        answer = attempt.answers.get(body.task_id)
        if not answer: raise HTTPException(422, 'Открытый ответ не предоставлен')
        if not app.state.llm.enabled:
            raise HTTPException(503, 'ИИ выключен. Оцените ответ вручную')
        if not suggestion_slots.acquire(blocking=False):
            raise HTTPException(503, 'Модель занята; повторите запрос позже', headers={'Retry-After': '5'})
        try:
            with suggestion_lock:
                calls = suggestion_calls[user.id]
                current_time = monotonic()
                while calls and current_time - calls[0] >= 60: calls.popleft()
                if len(calls) >= 10: raise HTTPException(429, 'Лимит ИИ-запросов: 10 в минуту', headers={'Retry-After': '60'})
                calls.append(current_time)
            try:
                result = suggest_review(task, answer, app.state.llm)
            except GenerationUnavailable:
                raise HTTPException(503, 'Модель недоступна. Оцените ответ вручную')
            except GenerationRejected:
                raise HTTPException(502, 'Ответ модели не прошёл проверку. Оцените ответ вручную или повторите запрос')
            audit(db, user, 'bank.review-suggestion:' + result.source, attempt.id); db.commit()
            return result
        finally:
            suggestion_slots.release()

    @app.post('/api/v1/company/bank-attempts/{attempt_id}/review', tags=['Ручная проверка'], response_model=S.AttemptAuthor)
    def bank_review(attempt_id: str, body: S.ReviewInput, user=Depends(employer), db=Depends(db_session)):
        attempt = db.scalar(select(BankAttempt).where(BankAttempt.id == attempt_id).with_for_update())
        if not attempt: raise HTTPException(404, 'Попытка не найдена')
        version = db.get(BankVersion, attempt.version_id); owned_bank(db, version.bank_id, user)
        if attempt.status == 'in_progress': raise HTTPException(409, 'Ответ ещё не отправлен')
        task = next((task for task in version.document['tasks'] if task['id'] == body.task_id and task['type'] == 'open_response'), None)
        if not task: raise HTTPException(422, 'Ручная проверка допустима только для открытого ответа')
        if not attempt.answers.get(body.task_id): raise HTTPException(422, 'Открытый ответ не предоставлен')
        previous = db.scalar(select(BankReview).where(BankReview.attempt_id == attempt.id, BankReview.task_id == body.task_id))
        if previous:
            if previous.score == body.score and previous.feedback == body.feedback: return attempt_view(db, attempt, True)
            raise HTTPException(409, 'Оценка уже зафиксирована; существующая проверка неизменяема')
        db.add(BankReview(attempt_id=attempt.id, task_id=body.task_id, reviewer_id=user.id, score=body.score, feedback=body.feedback))
        db.flush(); score_attempt(db, attempt); audit(db, user, 'bank.reviewed', attempt.id); db.commit()
        return attempt_view(db, attempt, True)

    def runner_auth(authorization: str | None = Header(default=None)):
        token = os.environ.get('FSP_RUNNER_TOKEN', '')
        if not token: raise HTTPException(503, 'Runner не настроен')
        if not authorization or not secrets.compare_digest(authorization, 'Bearer '+token):
            raise HTTPException(403, 'Runner не авторизован')

    @app.post('/internal/runner/claim', tags=['Внутренний runner'], response_model=S.RunnerClaim)
    def runner_claim(_=Depends(runner_auth), db=Depends(db_session)):
        expired = list(db.scalars(select(BankCodeJob).where(BankCodeJob.status == 'running', BankCodeJob.lease_expires_at < now()).with_for_update(skip_locked=True)))
        for job in expired:
            job.lease_token_hash = None; job.lease_expires_at = None
            if job.retries < 1: job.retries += 1; job.status = 'queued'
            else:
                job.status = 'failed'; job.error_code = 'runtime_unavailable'; job.finished_at = now()
                job.result = {'status': 'system_error', 'passed_tests': 0, 'total_tests': 0, 'score': 0, 'runtime_version': '', 'duration_ms': 0}
                attempt = db.scalar(select(BankAttempt).where(BankAttempt.id == job.attempt_id).with_for_update())
                if attempt.submitted_at: score_attempt(db, attempt)
        db.flush()
        job = db.scalar(select(BankCodeJob).where(BankCodeJob.status == 'queued').order_by(BankCodeJob.created_at).with_for_update(skip_locked=True))
        if not job: db.commit(); return {'job': None}
        lease = secrets.token_urlsafe(32)
        changed = db.execute(update(BankCodeJob).where(BankCodeJob.id == job.id, BankCodeJob.status == 'queued')
            .values(status='running', lease_token_hash=sha256(lease.encode()).hexdigest(), lease_expires_at=now()+timedelta(seconds=900)))
        if changed.rowcount != 1: db.rollback(); return {'job': None}
        attempt = db.scalar(select(BankAttempt).where(BankAttempt.id == job.attempt_id).with_for_update())
        task = next(task for task in db.get(BankVersion, attempt.version_id).document['tasks'] if task['id'] == job.task_id)
        tests = [{'stdin': case['input'], 'setup': case['setup'],
                  'expected': json.loads(case['output']) if task['language'] == 'sql' else case['output']}
                 for case in task['hidden_tests']]
        payload = {'id': job.id, 'lease_token': lease, 'language': task['language'], 'source': job.source,
                   'tests': tests, 'time_limit_seconds': task['runtime_limits']['wall_seconds']}
        db.commit(); return {'job': payload}

    @app.post('/internal/runner/jobs/{job_id}/result', tags=['Внутренний runner'], response_model=S.Saved)
    def runner_result(job_id: str, body: S.RunnerResult, _=Depends(runner_auth), db=Depends(db_session)):
        job = db.scalar(select(BankCodeJob).where(BankCodeJob.id == job_id).with_for_update())
        if not job: raise HTTPException(404, 'Запуск не найден')
        if job.status != 'running' or not job.lease_token_hash or not secrets.compare_digest(job.lease_token_hash, sha256(body.lease_token.encode()).hexdigest()) or aware(job.lease_expires_at) <= now():
            raise HTTPException(409, 'Lease истёк или результат уже зафиксирован')
        attempt = db.scalar(select(BankAttempt).where(BankAttempt.id == job.attempt_id).with_for_update())
        task = next(task for task in db.get(BankVersion, attempt.version_id).document['tasks'] if task['id'] == job.task_id)
        total = len(task['hidden_tests'])
        if body.total != total or body.passed > total or (body.status == 'passed' and body.passed != total) or (body.status != 'passed' and body.passed == total):
            raise HTTPException(422, 'Результат не соответствует зафиксированным проверкам')
        if body.status == 'system_error' and job.retries < 1:
            job.retries += 1; job.status = 'queued'; job.lease_token_hash = None; job.lease_expires_at = None
            db.commit(); return {'saved': True}
        job.status = 'failed' if body.status == 'system_error' else 'completed'
        job.error_code = body.error_code; job.finished_at = now(); job.lease_token_hash = None; job.lease_expires_at = None
        job.result = {'status': body.status, 'passed_tests': body.passed, 'total_tests': total,
                      'score': round(body.passed/total*100, 2), 'runtime_version': body.runtime_version, 'duration_ms': body.duration_ms}
        if attempt.submitted_at: score_attempt(db, attempt)
        db.commit(); return {'saved': True}
