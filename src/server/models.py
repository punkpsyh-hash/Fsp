from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(120))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (CheckConstraint("salary_min >= 0"),
                      UniqueConstraint("fsp_member_id", name="uq_profiles_fsp_member_id"),
                      Index("ix_profiles_search", "published", "specialization", "confirmed_grade"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    specialization: Mapped[str] = mapped_column(String(30), default="backend")
    claimed_grade: Mapped[str] = mapped_column(String(20), default="junior")
    confirmed_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    formats: Mapped[list] = mapped_column(JSON, default=lambda: ["remote"])
    salary_min: Mapped[int] = mapped_column(default=100000)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    test_score: Mapped[float] = mapped_column(Float, default=0)
    grade_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fsp_state: Mapped[str] = mapped_column(String(30), default="none")
    fsp_previous_state: Mapped[str] = mapped_column(String(30), default="none")
    fsp_signal: Mapped[float] = mapped_column(Float, default=0)
    industry: Mapped[str] = mapped_column(String(50), default="it")
    resume: Mapped[dict] = mapped_column(JSON, default=dict)
    fsp_member_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fsp_evidence: Mapped[list] = mapped_column(JSON, default=list)
    activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Уровень добросовестности попытки, подтвердившей грейд; None — прежние данные без проверки.
    integrity_level: Mapped[str | None] = mapped_column(String(10), nullable=True)


class FspFlow(Base):
    """Запрос входа через mock ФСП ID (authorization code + PKCE); одноразовый, живёт 10 минут."""
    __tablename__ = "fsp_flows"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    verifier: Mapped[str] = mapped_column(String(128))
    challenge: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    member_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Contact(Base):
    __tablename__ = "contacts"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    value: Mapped[str] = mapped_column(String(254))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Mail(Base):
    __tablename__ = "mock_mail"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token: Mapped[str] = mapped_column(String(128))  # Только dev mail sink, не внешняя доставка.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    grade: Mapped[str] = mapped_column(String(20))
    seed: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    specialization: Mapped[str] = mapped_column(String(30), default="backend")
    blueprint_version: Mapped[str] = mapped_column(String(50), default="families-v3")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    # Полная форма хранится только на сервере; публичный DTO исключает ключи.
    question_form: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(default=0)
    # Сигналы добросовестности: типы событий, время, темп ответов. Без текста и содержимого.
    integrity: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Offer(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("company_id", "idempotency_key"),
                      CheckConstraint("salary_from > 0 AND salary_to >= salary_from"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str] = mapped_column(String(4000))
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    salary_basis: Mapped[str] = mapped_column(String(10))
    vacancy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="sent")
    contact_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Search(Base):
    __tablename__ = "search_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    query: Mapped[dict] = mapped_column(JSON)
    candidate_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    explanations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(50), default="weighted-v1")


class Shortlist(Base):
    __tablename__ = "shortlist"
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Company(Base):
    __tablename__ = "companies"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(4000), default="")
    industry: Mapped[str] = mapped_column(String(120), default="Информационные технологии")
    contact: Mapped[str] = mapped_column(String(254))
    verification: Mapped[str] = mapped_column(String(30), default="unverified")


class HiringNeed(Base):
    __tablename__ = "hiring_needs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(4000))
    query: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Vacancy(Base):
    __tablename__ = "vacancies"
    __table_args__ = (CheckConstraint("salary_from > 0 AND salary_to >= salary_from"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(4000))
    specialization: Mapped[str] = mapped_column(String(30))
    grade: Mapped[str] = mapped_column(String(20))
    skills: Mapped[list] = mapped_column(JSON)
    format: Mapped[str] = mapped_column(String(20))
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    salary_basis: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("vacancy_id", "candidate_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    contact_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Условия в момент отклика: последующее редактирование вакансии их не меняет.
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmployerTask(Base):
    __tablename__ = "employer_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000))
    specialization: Mapped[str] = mapped_column(String(30))
    grade: Mapped[str] = mapped_column(String(20))
    rubric: Mapped[str] = mapped_column(String(2000))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskResponse(Base):
    __tablename__ = "task_responses"
    __table_args__ = (UniqueConstraint("task_id", "candidate_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("employer_tasks.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    answer: Mapped[str] = mapped_column(String(4000))
    score: Mapped[int | None] = mapped_column(nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GradeEvent(Base):
    __tablename__ = "grade_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"))
    specialization: Mapped[str] = mapped_column(String(30))
    previous_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConfirmedTrack(Base):
    __tablename__ = "confirmed_tracks"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    specialization: Mapped[str] = mapped_column(String(30), primary_key=True)
    grade: Mapped[str] = mapped_column(String(20))
    skills: Mapped[list] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Метка относится к попытке, подтвердившей именно этот исторический трек.
    integrity_level: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ChatMessage(Base):
    """Сообщение между компанией и кандидатом; доступно, пока открыт контакт (приглашение принято или отклик активен)."""
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_thread", "company_id", "candidate_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    sender_role: Mapped[str] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
