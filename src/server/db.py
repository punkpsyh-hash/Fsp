import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from .models import Company, EmployerTask, HiringNeed, User, Profile, Contact, Vacancy, now


def database_url():
    return URL.create("postgresql+psycopg", username="fsp", password=os.environ.get("FSP_DB_PASSWORD"),
                      host=os.environ.get("FSP_DB_HOST", "127.0.0.1"),
                      port=int(os.environ.get("FSP_DB_PORT", "15432")), database="fsp")


def database(url):
    kwargs = {"pool_pre_ping": True}
    # FSP_SQLITE_POOL=1 (лёгкий локальный запуск): обычный пул и WAL, чтобы параллельные запросы браузера не делили
    # одно соединение. Иначе (тесты, in-memory) — одно общее соединение.
    pooled = os.environ.get("FSP_SQLITE_POOL") == "1"
    if str(url).startswith("sqlite") and pooled:
        kwargs.update(connect_args={"check_same_thread": False, "timeout": 30})
    elif str(url).startswith("sqlite"):
        kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
    elif make_url(url).drivername.startswith("postgresql"):
        # Сбой Docker-сети не должен оставлять запрос или проверку ждать бесконечно.
        options = str(make_url(url).query.get("options", ""))
        kwargs["connect_args"] = {"connect_timeout": 5, "keepalives_idle": 5,
                                  "keepalives_interval": 2, "keepalives_count": 3,
                                  "tcp_user_timeout": 15000,
                                  "options": options + " -cstatement_timeout=30000"}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def fk_enabled(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            if pooled:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=30000")
    return engine, sessionmaker(engine, expire_on_commit=False)


def seed_demo(factory):
    # Идемпотентный seed; существующие профили/предложения не перезаписываются.
    with factory() as db:
        for key, role, label in [("demo-candidate-a", "candidate", "Кандидат А"),
                                 ("demo-candidate-b", "candidate", "Кандидат Б"),
                                 ("demo-candidate-c", "candidate", "Кандидат В · Frontend"),
                                 ("demo-candidate-d", "candidate", "Кандидат Г · QA"),
                                 ("demo-candidate-e", "candidate", "Кандидат Д · UI/UX"),
                                 ("demo-employer-x", "employer", "Демо-команда X"),
                                 ("demo-employer-y", "employer", "Демо-команда Y")]:
            if db.get(User, key):
                continue
            email = key + "@example.invalid"
            db.add(User(id=key, role=role, label=label, email=email, verified=True, demo_seed=True))
            db.flush()
            if role == "candidate":
                spec={"demo-candidate-c":"frontend","demo-candidate-d":"qa","demo-candidate-e":"design"}.get(key,"backend")
                skills={"backend":["python","sql"],"frontend":["javascript","html","http"],"qa":["testing","sql","http"],"design":["ux","ui","html"]}[spec]
                db.add(Profile(user_id=key, specialization=spec, claimed_grade="junior",
                               confirmed_grade="junior", skills=skills, formats=["remote"],
                               published=True, salary_min=100000, test_score=90 if key.endswith("a") else 80,
                               assessed_at=now(), grade_changed_at=now()))
                db.add(Contact(user_id=key, value=email))
        for key in ('demo-employer-x','demo-employer-y'):
            if not db.get(Company,key):
                user=db.get(User,key)
                db.add(Company(user_id=key,name=user.label,contact=user.email,
                               description='Синтетическая ИТ-команда для проверки сценариев подбора и оценки.'))
        templates=[('backend','Backend-разработчик Python','Разработка API и запросов PostgreSQL; обработка повторов и защита контактов.', ['python','sql','http']),
                   ('frontend','Frontend-разработчик JavaScript','Интерфейсы с доступными формами; преобразования данных и обработка запросов.', ['javascript','html','http']),
                   ('qa','Инженер QA','Проверка границ и матриц входных данных; SQL-проверки и права доступа API.', ['testing','sql','http']),
                   ('design','UI/UX дизайнер','Проектирование интерфейсов: доступные цвета и сетка, метрики юзабилити, передача макетов в разработку.', ['ux','ui','html'])]
        for spec,title,description,skills in templates:
            vid='demo-vacancy-'+spec
            if not db.get(Vacancy,vid):
                db.add(Vacancy(id=vid,company_id='demo-employer-x',title=title,description=description,
                               specialization=spec,grade='junior',skills=skills,format='remote',
                               salary_from=100000,salary_to=180000,salary_basis='gross',status='published'))
            nid='demo-need-'+spec
            if not db.get(HiringNeed,nid):
                db.add(HiringNeed(id=nid,company_id='demo-employer-x',title=title,description=description,
                                 query={'specialization':spec,'grade':'junior','must_skills':skills[:1],
                                        'desired_skills':skills[1:],'format':'remote','salary_to':180000,'fsp_only':False}))
            tid='demo-task-'+spec
            if not db.get(EmployerTask,tid):
                db.add(EmployerTask(id=tid,company_id='demo-employer-x',title='Разбор прав доступа API · '+spec,
                                    description='Предложите план проверки: контакт после принятия доступен только компании-отправителю. Как проверить отзыв и повторное принятие?',
                                    specialization=spec,grade='junior',published=True,
                                    rubric='Оценить отрицательные проверки другой компании, отзыв grant и идемпотентность. Ответ 5–10 предложений; максимум 15 минут, без выполнения чужого кода.'))
        db.commit()
