"""FastAPI MVP, исключительно локальный режим на синтетических данных."""
from contextlib import asynccontextmanager
from datetime import timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from copy import deepcopy
from urllib.parse import urlencode
import html
import json
import os
import secrets
import subprocess
import sys
from collections import OrderedDict, defaultdict, deque
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.domain import Candidate, Need, rank, grade_result
from . import schemas as S
from . import fsp_id
from . import integrity as integ
from . import llm
from .assessment import CATALOG, VERSION, evaluate, questions, public_questions, public_question_form
from .assessment_feedback import feedback
from .skill_evidence import skill_evidence
from .work_requirements import desired_for_tasks, task_matches, WORK_TASKS_VERSION
from .security import password_hash, password_valid
from .mailer import send_link, smtp_configuration
from . import jury
from .product import attach_product
from .db import database, database_url, seed_demo
from .models import Application, Audit, Attempt, Company, ConfirmedTrack, Contact, FspFlow, GradeEvent, LoginSession, Mail, Offer, Profile, Search, Shortlist, User, Vacancy, now

ROOT = Path(__file__).resolve().parents[2]
# Валидация (docs/30): погрешность формы около 12 баллов. Результат в пределах полосы от порога считается неубедительным.
CONFIRMATION_BAND = float(os.environ.get("FSP_CONFIRMATION_BAND", "6"))
CONFIRMATION_WINDOW = timedelta(hours=24)
RATE_LIMIT_LEDGER_SIZE = 1024


def hashed(value):
    return sha256(value.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _bounded_history(ledger, key):
    history = ledger.get(key)
    if history is None:
        if len(ledger) >= RATE_LIMIT_LEDGER_SIZE:
            ledger.popitem(last=False)
        history = deque()
        ledger[key] = history
    else:
        ledger.move_to_end(key)
    return history


def create_app(url=None, demo=None, seed=True):
    demo = os.environ.get("FSP_DEMO_MODE") == "1" if demo is None else demo
    jury_config = jury.configuration()
    engine, factory = database(url if url is not None else database_url())

    @asynccontextmanager
    async def lifespan(app):
        if not demo:
            raise RuntimeError("Публичный запуск запрещён: нужен FSP_DEMO_MODE=1. Стенд предназначен только для локальной демонстрации на синтетических данных.")
        smtp_configuration()
        if seed:
            seed_demo(factory)
            from .bank_examples import seed_banks
            seed_banks(factory)
        if jury_config:
            jury.prepare_accounts(factory, jury_config)
        yield
        engine.dispose()

    api_description = (
        "Публичный конкурсный стенд с индивидуальными синтетическими аккаунтами без почты, ФИО и реальных контактов. "
        "Это не официальный API ФСП и не контур для персональных данных."
        if jury_config and jury_config['individual_registration'] else
        "Ограниченный конкурсный стенд с готовыми синтетическими аккаунтами и парольным входом. "
        "Это не официальный API ФСП и не контур для персональных данных."
        if jury_config else
        "Полный локальный mock-стенд: синтетические данные, локальная mock-почта и mock ФСП ID. "
        "Это не официальный API ФСП и не публичный контур для персональных данных."
    )
    app = FastAPI(title="ФСП · Карьерный профиль · конкурсный стенд", version="0.4.0", lifespan=lifespan,
                  description=api_description,
                  docs_url=None, openapi_url="/api/openapi.json", redoc_url=None,
                  responses={422: {"description": "Некорректные поля: code, message, request_id, details без исходных значений"}})
    app.state.engine, app.state.factory = engine, factory
    app.state.llm = llm.config_from_env()
    llm_calls, llm_lock = defaultdict(deque), Lock()
    # app доступен только в внутренних Compose-сетях; browser Origin остаётся прежним.
    extra_hosts = [h.strip() for h in os.environ.get("FSP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    extra_origins = {o.strip() for o in os.environ.get("FSP_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "app", *extra_hosts])
    auth_requests, auth_lock = OrderedDict(), Lock()
    registration_requests, registration_rate_lock = OrderedDict(), Lock()
    # Штатный entrypoint запускает один Uvicorn worker; lock делает проверку лимита и insert атомарными в процессе.
    registration_create_lock = Lock()
    integrity_requests, integrity_lock = defaultdict(deque), Lock()
    # Предел попыток входа в минуту с одного адреса; повышается только для быстрых автоматических прогонов.
    auth_limit = (jury_config['auth_rate_limit'] if jury_config and jury_config['individual_registration']
                  else max(30, int(os.environ.get("FSP_AUTH_RATE_LIMIT", "30"))))

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = str(uuid4())
        origin = request.headers.get("origin")
        if (request.url.path.rstrip('/') == '/api/v1/auth/jury-register'
                and not (jury_config and jury_config['individual_registration'])):
            return JSONResponse({"code": "http_404", "message": "Индивидуальная регистрация недоступна",
                                 "request_id": request.state.request_id}, status_code=404)
        if jury_config and jury.blocked(request.url.path):
            return JSONResponse({"code": "jury_mode", "message": "В показе жюри доступен только вход с паролем; регистрация, почта и загрузка резюме отключены", "request_id": request.state.request_id}, status_code=404)
        allowed = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (8470, 18080, 5173)} | extra_origins
        # Чужой Origin отклоняем до мутации rate-limit ledger: иначе чужая страница
        # может исчерпать квоту посетителя или общего NAT простой POST-формой.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed:
            return JSONResponse({"code": "origin_forbidden", "message": "Источник запроса не разрешён", "request_id": request.state.request_id}, status_code=403)
        if request.method == "POST" and request.url.path.startswith("/api/v1/auth/"):
            key = hashed(request.client.host if request.client else "local")
            current = monotonic()
            with auth_lock:
                history = _bounded_history(auth_requests, key)
                while history and history[0] <= current-60: history.popleft()
                if len(history) >= auth_limit:
                    return JSONResponse({"code":"rate_limit","message":"Слишком много попыток входа. Подождите минуту","request_id":request.state.request_id},status_code=429,headers={"Retry-After":"60"})
                history.append(current)
            if (jury_config and jury_config['individual_registration']
                    and request.url.path.rstrip('/') == '/api/v1/auth/jury-register'):
                with registration_rate_lock:
                    # Ограничитель не должен бесконечно расти от случайных адресов сканеров.
                    history = _bounded_history(registration_requests, key)
                    while history and history[0] <= current - 3600:
                        history.popleft()
                    if len(history) >= jury_config['registration_rate_limit']:
                        return JSONResponse({"code": "rate_limit", "message": "Слишком много регистраций. Повторите позже",
                                             "request_id": request.state.request_id}, status_code=429,
                                            headers={"Retry-After": "3600"})
                    history.append(current)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith(("/api/", "/internal/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"code": f"http_{error.status_code}", "message": error.detail,
                             "request_id": request.state.request_id}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({"code": "validation", "message": "Проверьте поля запроса",
                             "details": [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in error.errors()],
                             "request_id": request.state.request_id}, status_code=422)

    def db_session():
        with factory() as db:
            yield db

    def actor(request: Request, db=Depends(db_session)):
        token = request.cookies.get("fsp_session", "")
        session = db.get(LoginSession, hashed(token))
        if not session or aware(session.expires_at) <= now():
            raise HTTPException(401, "Войдите в тестовый аккаунт")
        user = db.get(User, session.user_id)
        if not user or not user.verified:
            raise HTTPException(401, "Подтвердите адрес")
        if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
            raise HTTPException(403, "Отсутствует корректный CSRF-токен")
        request.state.session = session
        return user

    def candidate(user=Depends(actor)):
        if user.role != "candidate":
            raise HTTPException(403, "Доступ только кандидату")
        return user

    def employer(user=Depends(actor)):
        if user.role != "employer":
            raise HTTPException(403, "Доступ только работодателю")
        return user

    def audit(db, user, action, subject):
        db.add(Audit(actor_id=user.id, action=action, subject_id=subject))

    def login(db, user, response, old_token=""):
        if old_token:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == hashed(old_token)))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=hashed(token), user_id=user.id, csrf=csrf, expires_at=now() + timedelta(hours=8)))
        db.commit()
        response.set_cookie("fsp_session", token, httponly=True, samesite="strict", max_age=8*3600, path="/api", secure=os.environ.get("FSP_COOKIE_SECURE") == "1")
        return {"id": user.id, "role": user.role, "label": user.label, "email": user.email,
                "csrf": csrf, "demo": True}

    def own_profile(db, user):
        p = db.get(Profile, user.id)
        if not p:
            raise HTTPException(404, "Профиль не найден")
        return p

    def profile_alias(p):
        return {"demo-candidate-a": "P-104", "demo-candidate-b": "P-207"}.get(p.user_id, "P-"+hashed(p.user_id)[:8].upper())

    def public_profile(p):
        return {"id": p.user_id, "alias": profile_alias(p), "specialization": p.specialization, "confirmed_grade": p.confirmed_grade,
                "skills": p.skills, "formats": p.formats, "salary_min": p.salary_min, "test_score": p.test_score,
                "assessed_at": p.assessed_at, "integrity_level": "review" if p.integrity_level == "flagged" else p.integrity_level, "fsp_state": p.fsp_state,
                "fsp_evidence": p.fsp_evidence, "activity_at": p.activity_at,
                "experience": {key:p.resume.get(key,[] if key!='years_experience' else 0) for key in ('years_experience','roles','soft_skills')},
                "skill_evidence": skill_evidence(object_session(p), p), "demo": True}

    def permitted_contact(db, company_id, candidate_id):
        offer = db.scalar(select(Offer.id).where(Offer.company_id == company_id, Offer.candidate_id == candidate_id,
                                                Offer.status == "accepted", Offer.contact_revoked.is_(False))) is not None
        applied = db.scalar(select(Application.id).where(Application.company_id==company_id,Application.candidate_id==candidate_id,
                                                        Application.status.in_(['sent','viewed','accepted']),Application.contact_revoked.is_(False))) is not None
        return offer or applied

    def offer_view(db, o, user):
        company = db.get(User, o.company_id)
        company_profile = db.get(Company, o.company_id)
        contact = db.get(Contact, o.candidate_id)
        status = "expired" if o.status in {"sent", "viewed"} and aware(o.expires_at) <= now() else o.status
        result = {"id": o.id, "company_id": o.company_id, "company_name": company_profile.name if company_profile else company.label,
                  "company_contact": company_profile.contact if company_profile else company.email, "candidate_id": o.candidate_id, "description": o.description,
                  "salary_from": o.salary_from, "salary_to": o.salary_to, "salary_basis": o.salary_basis,
                  "currency": "RUB", "vacancy_id": o.vacancy_id, "status": status, "expires_at": o.expires_at,
                  "contact_revoked": o.contact_revoked, "demo": True}
        p = db.get(Profile, o.candidate_id)
        result["candidate_alias"] = profile_alias(p)
        if user.role == "employer" and permitted_contact(db, user.id, o.candidate_id) and contact:
            result["contact"] = contact.value
        return result

    @app.get("/api/health", tags=["Состояние"])
    def health(db=Depends(db_session)):
        db.execute(text("SELECT 1"))
        auth_mode = ("individual" if jury_config and jury_config['individual_registration']
                     else "shared-password" if jury_config else "local")
        return {"status": "ok", "mode": "jury-demo" if jury_config else "local-demo",
                "auth_mode": auth_mode, "version": "0.4.0"}

    @app.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
    def privacy_policy():
        return jury.policy_page('privacy', jury_config)

    @app.get("/legal/recommendations", response_class=HTMLResponse, include_in_schema=False)
    def recommendation_rules():
        return jury.policy_page('recommendations', jury_config)

    @app.get("/api/v1/auth/demo-accounts", tags=["Mock-идентификация"])
    def accounts(db=Depends(db_session)):
        if not demo_login_enabled():
            raise HTTPException(404, "Демо-вход отключён")
        return [{"id": u.id, "label": u.label, "role": u.role} for u in db.scalars(select(User).where(User.demo_seed.is_(True)))]

    @app.post("/api/v1/auth/demo-login", tags=["Mock-идентификация"])
    def demo_login(body: S.DemoLogin, response: Response, request: Request, db=Depends(db_session)):
        if not demo_login_enabled():
            raise HTTPException(404, "Демо-вход отключён")
        user = db.get(User, body.user_id)
        if not user or not user.demo_seed:
            raise HTTPException(404, "Тестовый аккаунт не найден")
        return login(db, user, response, request.cookies.get("fsp_session", ""))

    def sink_enabled():
        # Токены в открытом виде только в локальной demo-почте; при SMTP или FSP_MOCK_MAIL=0 их нет в БД и API.
        return not os.environ.get("FSP_SMTP_HOST") and os.environ.get("FSP_MOCK_MAIL", "1") != "0"

    def demo_login_enabled():
        return os.environ.get("FSP_DEMO_LOGIN", "1") != "0"

    def queue_mail(db, user):
        token = secrets.token_urlsafe(32)
        db.execute(delete(Mail).where(Mail.user_id == user.id))
        db.add(Mail(user_id=user.id, token=token if sink_enabled() else "hidden", token_hash=hashed(token), expires_at=now()+timedelta(minutes=30)))
        return token

    def deliver_mail(db,user,token):
        try:
            transport=send_link(user.email,token)
            return {"transport":transport,"delivery":"ready","demo":True}
        except (OSError,ValueError):
            # Запись подтверждения уже сохранена; можно повторить запрос ссылки.
            return {"transport":"smtp","delivery":"failed","message":"SMTP недоступен. Проверьте локальную конфигурацию и запросите письмо повторно","demo":True}

    @app.post("/api/v1/auth/jury-register", status_code=201, response_model=S.JurySession, tags=["Вход"])
    def jury_register(body: S.JuryRegister, response: Response, request: Request, db=Depends(db_session)):
        if not jury_config or not jury_config['individual_registration']:
            raise HTTPException(404, "Индивидуальная регистрация недоступна")
        with registration_create_lock:
            old_token = request.cookies.get("fsp_session", "")
            old_session = db.get(LoginSession, hashed(old_token)) if old_token else None
            if old_session and aware(old_session.expires_at) > now():
                raise HTTPException(409, "Сначала выйдите из текущего аккаунта")
            count = db.scalar(select(func.count()).select_from(User).where(User.demo_seed.is_(False)))
            if count >= jury_config['max_individual_accounts']:
                raise HTTPException(429, "Лимит индивидуальных аккаунтов стенда исчерпан",
                                    headers={"Retry-After": "3600"})
            identifier = "jury-" + secrets.token_hex(16)
            email = identifier + "@example.invalid"
            suffix = identifier[-8:].upper()
            label = ("Кандидат " if body.role == "candidate" else "Работодатель ") + suffix
            user = User(id=identifier, email=email, role=body.role, label=label, verified=True,
                        demo_seed=False, password_hash=password_hash(body.password))
            try:
                db.add(user)
                db.flush()
                if body.role == "candidate":
                    db.add(Profile(user_id=identifier))
                    db.add(Contact(user_id=identifier, value=email))
                else:
                    db.add(Company(user_id=identifier, name=label, contact=email,
                                   description="Синтетическая компания индивидуального участника стенда."))
                audit(db, user, "synthetic_demo_terms:v1", identifier)
                db.flush()
            except IntegrityError:
                db.rollback()
                raise HTTPException(503, "Не удалось создать синтетический аккаунт. Повторите запрос")
            account = login(db, user, response, old_token)
            return {**account, "email": email}

    @app.post("/api/v1/auth/register", status_code=201, tags=["Mock-идентификация"])
    def register(body: S.Register, db=Depends(db_session)):
        if db.scalar(select(User).where(User.email == body.email)):
            raise HTTPException(409, "Этот демонстрационный адрес уже зарегистрирован")
        user = User(email=body.email, role=body.role, label=body.label,
                    password_hash=password_hash(body.password) if body.password else None)
        try:
            db.add(user)
            db.flush()
            if user.role == "candidate":
                db.add(Profile(user_id=user.id))
                db.add(Contact(user_id=user.id, value=body.email))
            audit(db, user, "processing_consent:demo-v1", user.id)
            token = queue_mail(db, user)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Адрес уже зарегистрирован")
        delivery=deliver_mail(db,user,token)
        return {"message": "Ссылка подтверждения подготовлена; проверьте локальную почту", **delivery}

    @app.post("/api/v1/auth/password-login", tags=["Вход"])
    def password_login(body:S.PasswordLogin,response:Response,request:Request,db=Depends(db_session)):
        user=db.scalar(select(User).where(User.email==body.email))
        # Сопоставимое время для неизвестного адреса и неверного пароля.
        valid=password_valid(body.password,user.password_hash if user and user.password_hash else dummy_password)
        if (not user or not valid or
                (jury_config and jury_config['individual_registration'] and user.demo_seed)):
            raise HTTPException(401,"Неверный адрес или пароль")
        if not user.verified:raise HTTPException(403,"Сначала подтвердите адрес")
        return login(db,user,response,request.cookies.get("fsp_session",""))

    dummy_password=password_hash(secrets.token_urlsafe(24))

    @app.post("/api/v1/auth/login", tags=["Mock-идентификация"])
    def request_login(body: S.Email, db=Depends(db_session)):
        user = db.scalar(select(User).where(User.email == body.email))
        if user:
            token = queue_mail(db, user)
            db.commit()
            deliver_mail(db,user,token)
        return {"message": "Если адрес зарегистрирован, ссылка помещена в mock-почту", "demo": True}

    @app.get("/api/v1/auth/mock-mail", tags=["Mock-почта"])
    def mail_sink(db=Depends(db_session)):
        if not sink_enabled():
            raise HTTPException(404, "Локальная почта отключена")
        return [{"id": m.id, "email": db.get(User, m.user_id).email, "token": m.token,
                 "expires_at": m.expires_at, "demo": True} for m in db.scalars(select(Mail).where(Mail.used.is_(False), Mail.expires_at > now()))]

    @app.post("/api/v1/auth/verify", tags=["Mock-идентификация"])
    def verify(body: S.Verify, response: Response, request: Request, db=Depends(db_session)):
        mail = db.scalar(select(Mail).where(Mail.token_hash == hashed(body.token)).with_for_update())
        if not mail or mail.used or aware(mail.expires_at) <= now():
            raise HTTPException(409, "Ссылка использована или срок истёк")
        mail.used = True
        mail.token = "consumed"
        user = db.get(User, mail.user_id)
        user.verified = True
        return login(db, user, response, request.cookies.get("fsp_session", ""))

    @app.get("/api/v1/me", tags=["Сессия"])
    def me(request: Request, user=Depends(actor)):
        return {"id": user.id, "role": user.role, "label": user.label, "csrf": request.state.session.csrf,
                "email": user.email, "demo": True}

    @app.post("/api/v1/auth/logout", status_code=204, tags=["Сессия"])
    def logout(request: Request, response: Response, user=Depends(actor), db=Depends(db_session)):
        db.delete(db.get(LoginSession, request.state.session.token_hash))
        db.commit()
        response.delete_cookie("fsp_session", path="/api")

    @app.get("/api/v1/candidate/profile", tags=["Профиль"])
    def get_profile(user=Depends(candidate), db=Depends(db_session)):
        p = own_profile(db, user)
        grants = {o.company_id for o in db.scalars(select(Offer).where(Offer.candidate_id == user.id, Offer.status == "accepted", Offer.contact_revoked.is_(False)))}
        grants |= {a.company_id for a in db.scalars(select(Application).where(Application.candidate_id==user.id,Application.status.in_(['sent','viewed','accepted']),Application.contact_revoked.is_(False)))}
        return {**public_profile(p), "claimed_grade": p.claimed_grade, "published": p.published,
                "industry":p.industry,"resume":p.resume,"fsp_member_id":p.fsp_member_id,
                "contact": db.get(Contact, user.id).value, "grade_changed_at": p.grade_changed_at,
                "contact_grants": [{"id": cid, "label": db.get(User, cid).label} for cid in sorted(grants)]}

    @app.post("/api/v1/candidate/resume-preview",tags=["Профиль"])
    async def resume_preview(request:Request,user=Depends(candidate)):
        if request.headers.get('content-type','').split(';')[0]!='application/pdf':
            raise HTTPException(415,"Передайте файл PDF")
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>2*1024*1024:raise HTTPException(413,"Максимальный размер PDF — 2 МБ")
        from starlette.concurrency import run_in_threadpool
        def parse():
            try:
                result=subprocess.run([sys.executable,'-m','src.server.resume_parser'],input=bytes(data),capture_output=True,timeout=6,cwd=ROOT)
                if result.returncode:raise HTTPException(422,"PDF не удалось безопасно разобрать. Используйте ручную форму")
                return json.loads(result.stdout)
            except subprocess.TimeoutExpired:
                raise HTTPException(422,"Разбор PDF превысил лимит времени")
        return await run_in_threadpool(parse)

    @app.put("/api/v1/candidate/profile", tags=["Профиль"])
    def update_profile(body: S.ProfileInput, user=Depends(candidate), db=Depends(db_session)):
        p = db.scalar(select(Profile).where(Profile.user_id==user.id).with_for_update())
        if p.specialization != body.specialization:
            # Самоописание не переносит подтверждение между специализациями.
            if p.confirmed_grade and p.assessed_at and p.grade_changed_at:
                track=db.get(ConfirmedTrack,(user.id,p.specialization))
                if not track:track=ConfirmedTrack(user_id=user.id,specialization=p.specialization);db.add(track)
                track.grade,track.skills,track.score,track.assessed_at,track.changed_at=p.confirmed_grade,p.skills,p.test_score,p.assessed_at,p.grade_changed_at
                track.integrity_level=p.integrity_level
                db.flush()
            target=db.get(ConfirmedTrack,(user.id,body.specialization))
            p.confirmed_grade,p.skills,p.test_score,p.assessed_at,p.grade_changed_at=(target.grade,target.skills,target.score,target.assessed_at,target.changed_at) if target else (None,[],0,None,None)
            p.integrity_level=target.integrity_level if target else None
            p.published=False
        p.specialization, p.claimed_grade = body.specialization, body.claimed_grade
        p.industry,p.resume=body.industry,body.resume.model_dump()
        p.salary_min, p.formats = body.salary_min, sorted(set(body.formats))
        db.get(Contact, user.id).value = body.contact
        audit(db, user, "profile.updated", user.id)
        db.commit()
        return {"saved": True}

    @app.post("/api/v1/candidate/consents", tags=["Приватность"])
    def consent(body: S.ConsentInput, user=Depends(candidate), db=Depends(db_session)):
        p = own_profile(db, user)
        if body.published and not p.confirmed_grade:
            raise HTTPException(409, "Сначала завершите демонстрационную оценку")
        p.published = body.published
        audit(db, user, "publication.granted:demo-consent-v1" if body.published else "publication.revoked:demo-consent-v1", user.id)
        db.commit()
        return {"published": p.published}

    @app.delete("/api/v1/candidate/contacts/{company_id}", status_code=204, tags=["Приватность"])
    def revoke(company_id: str, user=Depends(candidate), db=Depends(db_session)):
        offers = db.scalars(select(Offer).where(Offer.candidate_id == user.id, Offer.company_id == company_id).with_for_update())
        for offer in offers:
            offer.contact_revoked = True
        for application in db.scalars(select(Application).where(Application.candidate_id==user.id,Application.company_id==company_id).with_for_update()):
            application.contact_revoked=True
        audit(db, user, "contact.revoked", company_id)
        db.commit()

    def attempt_view(attempt):
        form = attempt.question_form or questions(attempt.seed, attempt.grade, attempt.specialization, attempt.blueprint_version)
        pending = bool((attempt.result or {}).get("needs_confirmation") or
                       ((attempt.result or {}).get("integrity") or {}).get("hold"))
        if pending:
            db=object_session(attempt)
            queue, visited = [attempt.id], set()
            while queue and pending:
                previous=queue.pop()
                if previous in visited:
                    continue
                visited.add(previous)
                children=db.scalars(select(Attempt).where(
                    Attempt.candidate_id==attempt.candidate_id, Attempt.submitted_at.is_not(None),
                    (Attempt.context["parent"].as_string()==previous) |
                    (Attempt.context["recheck_of"].as_string()==previous)))
                for child in children:
                    result=child.result or {}
                    if result and not result.get("needs_confirmation") and not (result.get("integrity") or {}).get("hold"):
                        pending=False
                        break
                    queue.append(child.id)
        return {"id": attempt.id, "questions": public_question_form(form),
                "grade": attempt.grade, "specialization": attempt.specialization,
                "context": attempt.context, "version": attempt.blueprint_version,
                "result": attempt.result, "answers": attempt.answers, "revision": attempt.revision,
                # Разбор открыт только владельцу завершённой попытки. Он не меняет
                # сохранённый результат и не раскрывает эталон в активной форме.
                "feedback": feedback(form, attempt.answers, attempt.grade, attempt.blueprint_version)
                    if attempt.submitted_at and attempt.result is not None and not pending else None,
                "expires_at": aware(attempt.created_at)+timedelta(minutes=60), "demo": True}

    @app.get("/api/v1/candidate/active-assessment", tags=["Оценка"])
    def active_assessment(user=Depends(candidate), db=Depends(db_session)):
        attempt=db.scalar(select(Attempt).where(Attempt.candidate_id==user.id, Attempt.submitted_at.is_(None),
                           Attempt.created_at>now()-timedelta(minutes=60)).order_by(Attempt.created_at.desc()))
        return attempt_view(attempt) if attempt else None

    @app.post("/api/v1/assessments/attempts", status_code=201, tags=["Демо-оценка"])
    def start_attempt(body: S.AttemptInput, user=Depends(candidate), db=Depends(db_session)):
        p = db.scalar(select(Profile).where(Profile.user_id == user.id).with_for_update())
        if p.specialization!=body.specialization:raise HTTPException(409,"Выберите эту специализацию в профиле перед оценкой")
        context={"source":"catalog","skills":CATALOG[body.specialization]["skills"]}
        if body.vacancy_id:
            vacancy=db.get(Vacancy,body.vacancy_id)
            if not vacancy or vacancy.status!='published' or vacancy.specialization!=body.specialization or vacancy.grade!=body.grade:
                raise HTTPException(404,"Подходящая опубликованная вакансия не найдена")
            context={"source":"vacancy","vacancy_id":vacancy.id,"title":vacancy.title,"version":vacancy.version,"skills":vacancy.skills}
        previous = db.scalar(select(Attempt).where(Attempt.candidate_id == user.id, Attempt.grade == body.grade,Attempt.specialization==body.specialization).order_by(Attempt.created_at.desc()))
        if previous and not previous.submitted_at and aware(previous.created_at)+timedelta(minutes=60) > now():
            return attempt_view(previous)
        held = bool(previous and ((previous.result or {}).get('integrity') or {}).get('hold'))
        if held:
            if (previous.context or {}).get('recheck_of') and aware(previous.submitted_at)+timedelta(days=14) > now():
                raise HTTPException(409, "Перепроверка снова требует разбора. Следующая форма доступна через 14 суток")
            context = {**context, "recheck_of": previous.id}
        # Неубедительный результат у порога не сжигает попытку: решение откладывается до подтверждающей формы.
        inconclusive = bool(previous and previous.submitted_at and (previous.result or {}).get('needs_confirmation'))
        if inconclusive and aware(previous.submitted_at)+CONFIRMATION_WINDOW > now():
            context = {**context, "stage": 2, "parent": previous.id}
        if previous and previous.submitted_at and not held and not inconclusive and aware(previous.submitted_at)+timedelta(days=14) > now():
            raise HTTPException(409, "Повтор этой формы доступен через 14 суток; можно выбрать другой грейд")
        rank = {"junior": 0, "middle": 1}
        if p.confirmed_grade and rank[body.grade] > rank[p.confirmed_grade] and p.grade_changed_at and aware(p.grade_changed_at)+timedelta(days=90) > now():
            raise HTTPException(409, "Повышение подтверждённого демо-грейда доступно через 90 суток; понизить уровень можно сразу")
        attempt = Attempt(candidate_id=user.id, grade=body.grade,specialization=body.specialization,blueprint_version=VERSION,context=context, seed=secrets.randbelow(2**31))
        attempt.question_form=[{**row, 'id': secrets.token_hex(12)} for row in
                               questions(attempt.seed, attempt.grade, attempt.specialization, attempt.blueprint_version)]
        db.add(attempt)
        db.commit()
        return attempt_view(attempt)

    @app.get("/api/v1/assessments/attempts/{attempt_id}", tags=["Демо-оценка"])
    def get_attempt(attempt_id: str, user=Depends(candidate), db=Depends(db_session)):
        attempt = db.get(Attempt, attempt_id)
        if not attempt or attempt.candidate_id != user.id:
            raise HTTPException(404, "Попытка не найдена")
        return attempt_view(attempt)

    @app.put("/api/v1/assessments/attempts/{attempt_id}/draft", tags=["Оценка"])
    def save_attempt_draft(attempt_id: str, body: S.DraftAnswers, user=Depends(candidate), db=Depends(db_session)):
        attempt=db.scalar(select(Attempt).where(Attempt.id==attempt_id, Attempt.candidate_id==user.id).with_for_update())
        if not attempt: raise HTTPException(404,"Попытка не найдена")
        if attempt.submitted_at or aware(attempt.created_at)+timedelta(minutes=60)<=now():
            raise HTTPException(409,"Попытка завершена или истекла; черновик сохранён")
        if attempt.revision!=body.expected_revision:
            raise HTTPException(409,"Ответы изменились в другой вкладке. Загрузите сохранённую попытку перед повтором")
        try: evaluate(attempt.seed,attempt.grade,body.answers,attempt.specialization,attempt.blueprint_version,form=attempt.question_form)
        except ValueError as error: raise HTTPException(422,str(error))
        state=integ.note_answers(deepcopy(attempt.integrity) if attempt.integrity else integ.new_state(),
                                 attempt.answers or {}, body.answers, (now()-aware(attempt.created_at)).total_seconds())
        changed=db.execute(update(Attempt).where(Attempt.id==attempt.id,Attempt.revision==body.expected_revision,
                           Attempt.submitted_at.is_(None)).values(answers=dict(body.answers),revision=body.expected_revision+1,integrity=state))
        if changed.rowcount!=1: raise HTTPException(409,"Ответы изменились параллельно; загрузите сохранённую попытку")
        audit(db,user,"assessment.draft",attempt.id); db.commit(); db.refresh(attempt)
        return attempt_view(attempt)

    @app.post("/api/v1/assessments/attempts/{attempt_id}/integrity", status_code=202, tags=["Оценка"],
              response_model=S.IntegrityAck, summary="Передать сигналы добросовестности активной попытки")
    def attempt_integrity(attempt_id: str, body: S.IntegrityBatch, user=Depends(candidate), db=Depends(db_session)):
        # Только проверенная учётная запись расходует свой бюджет. Общий IP
        # аудитории и неавторизованные запросы не отключают чужие мониторы.
        current = monotonic()
        with integrity_lock:
            history = integrity_requests[user.id]
            while history and history[0] <= current-60: history.popleft()
            if len(history) >= 60:
                raise HTTPException(429, "Слишком много событий оценки. Повторите через минуту", headers={"Retry-After":"60"})
            history.append(current)
        attempt=db.scalar(select(Attempt).where(Attempt.id==attempt_id, Attempt.candidate_id==user.id).with_for_update())
        if not attempt: raise HTTPException(404,"Попытка не найдена")
        if attempt.submitted_at or aware(attempt.created_at)+timedelta(minutes=60)<=now():
            raise HTTPException(409,"Попытка завершена или истекла")
        state=deepcopy(attempt.integrity) if attempt.integrity else integ.new_state()
        integ.record_events(state,[event.model_dump() for event in body.events],
                            (now()-aware(attempt.created_at)).total_seconds())
        attempt.integrity=state
        db.commit()
        return {"recorded":len(body.events)}

    @app.post("/api/v1/assessments/attempts/{attempt_id}/submit", tags=["Демо-оценка"])
    def submit(attempt_id: str, body: S.Answers, user=Depends(candidate), db=Depends(db_session)):
        attempt = db.scalar(select(Attempt).where(Attempt.id == attempt_id, Attempt.candidate_id == user.id).with_for_update())
        if not attempt:
            raise HTTPException(404, "Попытка не найдена")
        if attempt.submitted_at:
            return attempt.result
        if aware(attempt.created_at)+timedelta(minutes=60) <= now():
            raise HTTPException(409, "Истекло время попытки")
        p = db.scalar(select(Profile).where(Profile.user_id == user.id).with_for_update())
        if p.specialization!=attempt.specialization:raise HTTPException(409,"Специализация профиля изменилась; нужна новая форма")
        try:
            result = evaluate(attempt.seed, attempt.grade, body.answers,attempt.specialization,attempt.blueprint_version,form=attempt.question_form)
        except ValueError as error:raise HTTPException(422,str(error))
        # Сигналы добросовестности: темп считает сервер, события браузера присылает клиент.
        state=integ.note_answers(deepcopy(attempt.integrity) if attempt.integrity else integ.new_state(),
                                 attempt.answers or {}, body.answers, (now()-aware(attempt.created_at)).total_seconds())
        review=integ.assess(state, (now()-aware(attempt.created_at)).total_seconds())
        # Прошедший тест с сильными сигналами не получает подтверждение до перепроверки на новой форме.
        # Compose включает удержание; явный FSP_INTEGRITY_ENFORCE=0 предназначен для демонстрации.
        enforced=os.environ.get("FSP_INTEGRITY_ENFORCE", "1")=="1"
        hold=enforced and result["passed"] and review["level"]=="flagged"
        confirm=result["passed"] and not hold
        # Валидация (docs/30): SEM формы около 12 баллов; рядом с порогом итог при повторе может измениться.
        threshold=70 if attempt.grade=="junior" else 80
        parent=db.get(Attempt,attempt.context.get("parent")) if (attempt.context or {}).get("stage")==2 else None
        needs=False
        if parent is not None and parent.result:
            # Подтверждающая форма: итог считается по двум независимым формам одинакового состава.
            first=parent.result
            skills_total={}
            for part in (first["breakdown"],result["breakdown"]):
                for row in part:
                    mix=skills_total.setdefault(row["skill"],[0,0]);mix[0]+=row["correct"];mix[1]+=row["total"]
            breakdown=[{"skill":k,"correct":c,"total":n,"score":round(100*c/n,2)} for k,(c,n) in sorted(skills_total.items())]
            combined=round((first["score"]+result["score"])/2,2)
            result={**result,"score":combined,"skills":[b["skill"] for b in breakdown if b["score"]>=50],"breakdown":breakdown,
                    "passed":combined>=threshold,"stage":2,"stage_scores":[first["score"],result["score"]]}
            first_integrity=first.get("integrity") or {}
            levels={review["level"],first_integrity.get("level")}
            review={**review,"level":"flagged" if "flagged" in levels else "review" if "review" in levels else "clean",
                    "signals":[*(first_integrity.get("signals") or []),*review["signals"]]}
            hold=enforced and result["passed"] and review["level"]=="flagged"
            confirm=result["passed"] and not hold
        elif CONFIRMATION_BAND and abs(result["score"]-threshold)<=CONFIRMATION_BAND:
            needs=True
            confirm=False
            result={**result,"passed":False,"stage":1,"needs_confirmation":True}
        result={**result,"borderline":needs,"confirmed":confirm,"integrity":{"level":review["level"],"signals":review["signals"],"hold":hold,"enforced":enforced}}
        previous_grade=p.confirmed_grade
        try:
            grade = grade_result(p.confirmed_grade, attempt.grade, confirm, aware(p.grade_changed_at) if p.grade_changed_at else None, now())
        except ValueError as error:
            if str(error) != "grade_cooldown":
                raise HTTPException(409, str(error))
            # Состояние гонки: лимит наступил после старта попытки. Результат теста сохраняем, грейд не меняем.
            grade, confirm = p.confirmed_grade, False
            result = {**result, "confirmed": False, "cooldown": True}
        if confirm:
            if grade != p.confirmed_grade:
                p.grade_changed_at = now()
            p.confirmed_grade, p.skills, p.test_score, p.assessed_at = grade, result["skills"], result["score"], now()
            p.integrity_level = review["level"]
        attempt.submitted_at, attempt.score, attempt.result = now(), result["score"], result
        attempt.integrity={**state,"assessment":review}
        attempt.answers=dict(body.answers); attempt.revision+=1
        if not needs:
            db.add(GradeEvent(candidate_id=user.id,attempt_id=attempt.id,specialization=attempt.specialization,previous_grade=previous_grade,grade=p.confirmed_grade,passed=confirm))
        audit(db, user, "assessment.submitted:"+result["version"], attempt.id)
        db.commit()
        return result

    mock_idp = "/api/v1/auth/mock-fsp-id"   # под /auth/: общий лимит попыток входа
    callback_path = "/api/v1/candidate/fsp-id/callback"

    @app.get("/api/v1/auth/mock-fsp-id/.well-known/openid-configuration", tags=["ФСП mock"], response_model=dict,
             summary="OIDC discovery имитации ФСП ID")
    def fsp_discovery(request: Request):
        return fsp_id.discovery(str(request.base_url).rstrip("/") + mock_idp)

    @app.get("/api/v1/candidate/fsp-id/start", tags=["ФСП mock"], status_code=302, response_class=RedirectResponse,
             summary="Начать вход через ФСП ID (перенаправление на форму входа)")
    def fsp_start(user=Depends(candidate), db=Depends(db_session)):
        return RedirectResponse(fsp_id.start(db, user.id, mock_idp, callback_path), status_code=302)

    @app.get("/api/v1/auth/mock-fsp-id/authorize", tags=["ФСП mock"], response_class=HTMLResponse,
             summary="Форма входа имитации ФСП ID")
    def fsp_authorize_form(state: str = Query("", max_length=100), redirect_uri: str = Query("", max_length=200),
                           client_id: str = Query("", max_length=80), db=Depends(db_session)):
        if client_id != fsp_id.CLIENT_ID or redirect_uri != callback_path or fsp_id._flow(db, state) is None:
            return HTMLResponse(fsp_id.authorize_page({}, "Запрос входа недействителен или устарел"), status_code=400)
        return HTMLResponse(fsp_id.authorize_page({"state": state, "redirect_uri": redirect_uri}))

    @app.post("/api/v1/auth/mock-fsp-id/authorize", tags=["ФСП mock"], status_code=302, response_class=RedirectResponse,
              summary="Проверить ФСП ID и пароль, вернуть одноразовый код")
    async def fsp_authorize_submit(request: Request, db=Depends(db_session)):
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs((await request.body())[:4096].decode("utf-8", "replace")).items()}
        state, member = form.get("state", ""), form.get("member_id", "")[:40]
        if form.get("redirect_uri") != callback_path:
            return HTMLResponse(fsp_id.authorize_page({}, "Недопустимый адрес возврата"), status_code=400)
        code = fsp_id.authorize_submit(db, state, member, form.get("password", "")[:80])
        if code is None:
            return HTMLResponse(fsp_id.authorize_page({"state": state, "redirect_uri": callback_path}, "Неверный ФСП ID или пароль"), status_code=400)
        return RedirectResponse(callback_path + "?" + urlencode({"code": code, "state": state}), status_code=302)

    @app.post("/api/v1/auth/mock-fsp-id/token", tags=["ФСП mock"], response_model=S.FspTokenOut,
              summary="Обменять код и code_verifier (PKCE) на данные участника")
    def fsp_token(body: S.FspToken, db=Depends(db_session)):
        claims = fsp_id.exchange(db, body.code, body.code_verifier) if body.client_id == fsp_id.CLIENT_ID else None
        if claims is None:
            raise HTTPException(400, "invalid_grant")
        return {"token_type": "Bearer", "sub": claims["sub"], "scope": claims["scope"], "mock": True}

    @app.get(callback_path, tags=["ФСП mock"], status_code=302, response_class=RedirectResponse,
             summary="Завершить привязку ФСП ID к профилю кандидата")
    def fsp_callback(code: str = Query(max_length=200), state: str = Query(max_length=100),
                     user=Depends(candidate), db=Depends(db_session)):
        flow = db.get(FspFlow, state)
        claims = fsp_id.exchange(db, code, flow.verifier, state) if flow and flow.user_id == user.id else None
        if claims is None:
            return RedirectResponse("/candidate/privacy?fsp=failed", status_code=302)
        profile = db.scalar(select(Profile).where(Profile.user_id == user.id).with_for_update())
        status = fsp_id.link(db, profile, claims["sub"], os.environ.get("FSP_REGISTRY_UNAVAILABLE") == "1")
        audit(db, user, "fsp.link:" + status, user.id)
        db.commit()
        return RedirectResponse("/candidate/privacy?fsp=" + status, status_code=302)

    @app.delete("/api/v1/candidate/fsp-link", tags=["ФСП mock"], summary="Отвязать ФСП ID")
    def fsp(user=Depends(candidate), db=Depends(db_session)):
        p = own_profile(db, user)
        fsp_id.unlink(p)
        audit(db, user, "fsp.unlink", user.id)
        db.commit()
        return {"state": p.fsp_state, "previous_state": p.fsp_previous_state, "signal": p.fsp_signal, "demo": True}

    @app.post("/api/v1/company/searches", status_code=201, tags=["Подбор"])
    def search(body: S.SearchInput, user=Depends(employer), db=Depends(db_session)):
        # Префильтр в SQL: rank() всё равно отбрасывает другие специализацию и грейд, результат тот же.
        query=select(Profile).where(Profile.published.is_(True), Profile.specialization==body.specialization, Profile.confirmed_grade==body.grade)
        if body.fsp_only:query=query.where(Profile.fsp_signal>0)
        profiles = db.scalars(query).all()
        def freshness(p):
            dates=[aware(t) for t in [p.assessed_at,p.activity_at] if t]
            return min(1,max(0,1-(now()-max(dates)).days/180)) if dates else 0
        items = [Candidate(p.user_id, p.specialization, p.confirmed_grade, frozenset(p.skills), p.test_score,
                           p.fsp_signal, freshness(p),
                           p.published, frozenset(p.formats), p.salary_min) for p in profiles]
        task_skills = desired_for_tasks(body.work_tasks, body.specialization)
        need = Need(body.specialization, body.grade, frozenset(body.must_skills),
                    frozenset(body.desired_skills) | frozenset(task_skills), body.salary_to, body.format)
        ranked = rank(items, need)
        by_id = {p.user_id: p for p in profiles}
        rows=jsonable_encoder([{**public_profile(by_id[r["id"]]), **r,
                                "work_matches": task_matches(by_id[r["id"]].skills, body.work_tasks)} for r in ranked])
        # Snapshot никогда не содержит контакт: права проверяются при каждом чтении.
        saved = Search(company_id=user.id, query=body.model_dump(), candidate_ids=[r["id"] for r in ranked],
                       explanations=rows, algorithm_version=("weighted-v1+"+WORK_TASKS_VERSION if body.work_tasks else "weighted-v1"))
        db.add(saved)
        db.commit()
        return {"id": saved.id, "candidate_ids": saved.candidate_ids,
                "rows": rows, "created_at":saved.created_at, "algorithm_version":saved.algorithm_version, "demo": True}

    @app.post("/api/v1/company/searches/{search_id}/candidates/{candidate_id}/explanation", tags=["Подбор"],
              response_model=S.ExplanationOut, summary="Словесное объяснение попадания кандидата в подборку")
    def explain_candidate(search_id: str, candidate_id: str, user=Depends(employer), db=Depends(db_session)):
        saved = db.get(Search, search_id)
        row = next((r for r in (saved.explanations or []) if r.get("id") == candidate_id), None) if saved and saved.company_id == user.id else None
        profile=db.get(Profile,candidate_id) if row is not None else None
        if row is None or profile is None or not profile.published:
            raise HTTPException(404, "Строка подборки не найдена")
        with llm_lock:
            calls = llm_calls[user.id]
            current = monotonic()
            while calls and calls[0] <= current - 60: calls.popleft()
            if len(calls) >= 20:
                raise HTTPException(429, "Слишком много запросов объяснений. Подождите минуту", headers={"Retry-After": "60"})
            calls.append(current)
        # Шаблон всегда доступен; модель (если включена) получает только обезличенные факты из белого списка.
        result = llm.explain(row, app.state.llm)
        audit(db, user, "llm.explanation:" + result["source"], search_id)
        db.commit()
        return result

    @app.get("/api/v1/company/searches", tags=["Подбор"])
    def searches(user=Depends(employer), db=Depends(db_session)):
        return [{"id": s.id, "query": s.query, "created_at": s.created_at} for s in db.scalars(select(Search).where(Search.company_id == user.id).order_by(Search.created_at.desc()).limit(10))]

    @app.get("/api/v1/company/searches/page", tags=["Подбор"],
             summary="Получить страницу истории своих подборок")
    def searches_page(offset: int = Query(0, ge=0, le=2_147_483_647), limit: int = Query(8, ge=1, le=100),
                      user=Depends(employer), db=Depends(db_session)):
        # Отдельная операция сохраняет прежний list-контракт последних десяти.
        # Второй ключ обеспечивает однозначный порядок при равных timestamps.
        scope = Search.company_id == user.id
        total = db.scalar(select(func.count()).select_from(Search).where(scope))
        rows = db.scalars(select(Search).where(scope)
                          .order_by(Search.created_at.desc(), Search.id.desc())
                          .offset(offset).limit(limit))
        return {"items": [{"id": s.id, "query": s.query, "created_at": s.created_at} for s in rows],
                "total": total, "offset": offset, "limit": limit}

    @app.get("/api/v1/company/candidates/{candidate_id}", tags=["Подбор"])
    def candidate_detail(candidate_id: str, user=Depends(employer), db=Depends(db_session)):
        p = db.get(Profile, candidate_id)
        grant = permitted_contact(db, user.id, candidate_id)
        if not p or (not p.published and not grant):
            raise HTTPException(404, "Кандидат не найден")
        result = public_profile(p)
        if grant:
            result["contact"] = db.get(Contact, candidate_id).value
        return result

    @app.get("/api/v1/company/shortlist", tags=["Подбор"])
    def get_shortlist(user=Depends(employer), db=Depends(db_session)):
        ids = db.scalars(select(Shortlist.candidate_id).where(Shortlist.company_id == user.id)).all()
        return [public_profile(p) for cid in ids if (p := db.get(Profile, cid)) and p.published]

    @app.put("/api/v1/company/shortlist/{candidate_id}", status_code=204, tags=["Подбор"])
    def save_shortlist(candidate_id: str, user=Depends(employer), db=Depends(db_session)):
        p = db.get(Profile, candidate_id)
        if not p or not p.published:
            raise HTTPException(404, "Кандидат не найден")
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        if not db.get(Shortlist, (user.id, candidate_id)):
            db.add(Shortlist(company_id=user.id, candidate_id=candidate_id))
        db.commit()

    @app.delete("/api/v1/company/shortlist/{candidate_id}", status_code=204, tags=["Подбор"])
    def remove_shortlist(candidate_id: str, user=Depends(employer), db=Depends(db_session)):
        db.execute(delete(Shortlist).where(Shortlist.company_id == user.id, Shortlist.candidate_id == candidate_id))
        db.commit()

    @app.post("/api/v1/company/invitations", status_code=201, tags=["Приглашения"])
    def invite(body: S.OfferInput, idempotency_key: str = Header(min_length=8, max_length=128), user=Depends(employer), db=Depends(db_session)):
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        digest = hashed(json.dumps(body.model_dump(), sort_keys=True, ensure_ascii=False))
        previous = db.scalar(select(Offer).where(Offer.company_id == user.id, Offer.idempotency_key == idempotency_key))
        if previous:
            if previous.request_hash != digest:
                raise HTTPException(409, "Idempotency-Key уже использован с другим содержимым")
            return offer_view(db, previous, user)
        p = db.get(Profile, body.candidate_id)
        if body.vacancy_id:
            vacancy=db.get(Vacancy,body.vacancy_id)
            if not vacancy or vacancy.company_id!=user.id or vacancy.status!='published':
                raise HTTPException(404,"Вакансия компании не найдена")
        if not p or not p.published or not p.confirmed_grade:
            raise HTTPException(404, "Опубликованный подтверждённый профиль не найден")
        offer = Offer(company_id=user.id, **body.model_dump(), idempotency_key=idempotency_key,
                      request_hash=digest, expires_at=now()+timedelta(days=7))
        db.add(offer)
        db.flush()
        audit(db, user, "invitation.sent", offer.id)
        db.commit()
        return offer_view(db, offer, user)

    @app.get("/api/v1/company/invitations", tags=["Приглашения"])
    def company_offers(user=Depends(employer), db=Depends(db_session)):
        return [offer_view(db, o, user) for o in db.scalars(select(Offer).where(Offer.company_id == user.id).order_by(Offer.created_at.desc()))]

    @app.get("/api/v1/candidate/invitations", tags=["Приглашения"])
    def candidate_offers(user=Depends(candidate), db=Depends(db_session)):
        return [offer_view(db, o, user) for o in db.scalars(select(Offer).where(Offer.candidate_id == user.id).order_by(Offer.created_at.desc()))]

    @app.post("/api/v1/candidate/invitations/{offer_id}/view",tags=["Приглашения"])
    def view_offer(offer_id:str,user=Depends(candidate),db=Depends(db_session)):
        offer=db.scalar(select(Offer).where(Offer.id==offer_id,Offer.candidate_id==user.id).with_for_update())
        if not offer:raise HTTPException(404,"Приглашение не найдено")
        if offer.status=='sent' and aware(offer.expires_at)>now():
            offer.status='viewed';audit(db,user,'invitation.viewed',offer.id);db.commit()
        return offer_view(db,offer,user)

    @app.post("/api/v1/candidate/invitations/{offer_id}/decision", tags=["Приглашения"])
    def decide(offer_id: str, body: S.Decision, user=Depends(candidate), db=Depends(db_session)):
        offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.candidate_id == user.id).with_for_update())
        if not offer:
            raise HTTPException(404, "Приглашение не найдено")
        if offer.status == body.decision:
            return offer_view(db, offer, user)
        if offer.status not in {"sent", "viewed"}:
            raise HTTPException(409, "Приглашение уже завершено")
        if aware(offer.expires_at) <= now():
            offer.status = "expired"
            db.commit()
            raise HTTPException(409, "Приглашение истекло")
        offer.status = body.decision
        audit(db, user, "invitation."+body.decision, offer.id)
        db.commit()
        return offer_view(db, offer, user)

    @app.post("/api/v1/company/invitations/{offer_id}/withdraw", tags=["Приглашения"])
    def withdraw(offer_id: str, user=Depends(employer), db=Depends(db_session)):
        offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.company_id == user.id).with_for_update())
        if not offer:
            raise HTTPException(404, "Приглашение не найдено")
        if offer.status != "withdrawn":
            if offer.status not in {"sent", "viewed"}:
                raise HTTPException(409, "Завершённое приглашение нельзя отозвать")
            if aware(offer.expires_at) <= now():
                raise HTTPException(409, "Приглашение истекло")
            offer.status = "withdrawn"
            audit(db, user, "invitation.withdrawn", offer.id)
            db.commit()
        return offer_view(db, offer, user)

    def profile_pdf(p, contact=None):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from reportlab.lib.styles import ParagraphStyle
        bundled_font = ROOT/"resources"/"DejaVuSans.ttf"
        font = str(bundled_font) if bundled_font.is_file() else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        if not Path(font).is_file():
            raise HTTPException(503, "Для PDF требуется DejaVuSans")
        if "FspRU" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("FspRU", font))
        output = BytesIO()
        style = ParagraphStyle("body", fontName="FspRU", fontSize=11, leading=17)
        lines = ["ФСП · Демонстрационный профиль", "Только синтетические данные. Оценка не является профессиональной аттестацией.",
                 "ID: "+p.user_id, "Специализация: "+p.specialization, "Демо-грейд: "+str(p.confirmed_grade or "не подтверждён"),
                 "Проверенные демо-навыки: "+", ".join(p.skills),
                 "Технологии, заявленные кандидатом: "+", ".join(skill_evidence(object_session(p), p)['declared']),
                 "Практика учитывается отдельно и не присваивает глобальный грейд.", "ФСП mock: "+p.fsp_state,
                 "Дата экспорта: "+now().isoformat()]
        lines += ["Стаж: "+str(p.resume.get('years_experience',0))+" лет", "Роли: "+', '.join(p.resume.get('roles',[])),
                  "Софт-навыки (заявлены): "+', '.join(p.resume.get('soft_skills',[]))]
        if contact:
            lines += ["Имя: "+p.resume.get('full_name','Синтетический кандидат'),"Образование: "+p.resume.get('education',''),"О себе: "+p.resume.get('about','')]
            lines.append("Контакт, разрешённый получателю: "+contact)
        else:
            lines.append("Контакт скрыт")
        story = []
        for line in lines:
            story += [Paragraph(html.escape(line), style), Spacer(1, 10)]
        SimpleDocTemplate(output).build(story)
        return Response(output.getvalue(), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="fsp-profile.pdf"'})

    @app.get("/api/v1/candidate/profile.pdf", tags=["Экспорт"])
    def self_pdf(user=Depends(candidate), db=Depends(db_session)):
        return profile_pdf(own_profile(db, user), db.get(Contact, user.id).value)

    @app.get("/api/v1/company/candidates/{candidate_id}/profile.pdf", tags=["Экспорт"])
    def company_pdf(candidate_id: str, user=Depends(employer), db=Depends(db_session)):
        p = db.get(Profile, candidate_id)
        grant = permitted_contact(db, user.id, candidate_id)
        if not p or (not p.published and not grant):
            raise HTTPException(404, "Кандидат не найден")
        return profile_pdf(p, db.get(Contact, candidate_id).value if grant else None)

    attach_product(app,db_session,candidate,employer,actor,public_profile,profile_alias,permitted_contact,audit,aware)
    from .messaging import attach_messaging
    attach_messaging(app,db_session,candidate,employer,permitted_contact,profile_alias,audit)
    from .banks import install_banks
    install_banks(app,db_session,employer,candidate,audit,aware)

    @app.get("/api/docs", include_in_schema=False, response_class=HTMLResponse)
    def api_docs():
        lines = ["<!doctype html><html lang='ru'><meta charset='utf-8'><title>API ФСП MVP</title><h1>Локальный API ФСП MVP</h1>",
                 "<p>Синтетические данные. Identity, почта и ФСП — mock. <a href='/api/openapi.json'>Полный контракт OpenAPI</a></p>",
                 "<table><thead><tr><th>Метод</th><th>Путь</th><th>Операция</th></tr></thead><tbody>"]
        for path, methods in app.openapi()["paths"].items():
            for method, spec in methods.items():
                lines.append("<tr><td>"+html.escape(method.upper())+"</td><td>"+html.escape(path)+"</td><td>"+html.escape(spec.get("summary", ""))+"</td></tr>")
        return "".join(lines)+"</tbody></table></html>"

    @app.get("/artwork", include_in_schema=False)
    def artwork():
        return FileResponse(ROOT/"design"/"assets"/"editorial.png")

    dist = ROOT/"web"/"dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist/"assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(dist/"index.html")

    def contract():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["sessionCookie"] = {
            "type": "apiKey", "in": "cookie", "name": "fsp_session"}
        schema["components"]["securitySchemes"]["runnerBearer"]={"type":"http","scheme":"bearer",
            "description":"Секрет только worker/broker. Не сессия пользователя, не API ФСП."}
        for path, methods in schema["paths"].items():
            if path.startswith("/internal/runner/"):
                for spec in methods.values(): spec["security"]=[{"runnerBearer":[]}]
                continue
            if not path.startswith("/api/v1/") or path.startswith("/api/v1/auth/"):
                continue
            for method, spec in methods.items():
                spec["security"] = [{"sessionCookie": []}]
                if method not in {"get", "head"}:
                    spec.setdefault("parameters", []).append({"in": "header", "name": "X-CSRF-Token", "required": True,
                                                              "schema": {"type": "string"}, "description": "CSRF-токен текущей сессии из GET /api/v1/me"})
        # Logout требует те же сессию и CSRF, в отличие от dev-входа.
        logout_spec = schema["paths"]["/api/v1/auth/logout"]["post"]
        logout_spec["security"] = [{"sessionCookie": []}]
        logout_spec["parameters"] = [{"in": "header", "name": "X-CSRF-Token", "required": True, "schema": {"type": "string"}}]
        from .contract import enrich
        schema=enrich(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = contract
    return app


app = create_app()
