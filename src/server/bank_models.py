"""Версии наборов и попытки. Опубликованные документы не редактируются."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, now, uid


class TaskBank(Base):
    __tablename__ = 'task_banks'
    __table_args__ = (UniqueConstraint('owner_id', 'external_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(20), default='employer')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BankVersion(Base):
    __tablename__ = 'bank_versions'
    __table_args__ = (UniqueConstraint('bank_id', 'number'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    bank_id: Mapped[str] = mapped_column(ForeignKey('task_banks.id'), index=True)
    number: Mapped[int] = mapped_column(default=1)
    revision: Mapped[int] = mapped_column(default=1)
    state: Mapped[str] = mapped_column(String(20), default='draft')
    document: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BankImport(Base):
    __tablename__ = 'bank_imports'
    __table_args__ = (UniqueConstraint('owner_id', 'content_hash'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(200))
    document: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    bank_id: Mapped[str | None] = mapped_column(ForeignKey('task_banks.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BankAttempt(Base):
    __tablename__ = 'bank_attempts'
    __table_args__ = (UniqueConstraint('candidate_id', 'version_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey('bank_versions.id'), index=True)
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(30), default='in_progress')
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BankCodeJob(Base):
    __tablename__ = 'bank_code_jobs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('bank_attempts.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(32000))
    source_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retries: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BankReview(Base):
    __tablename__ = 'bank_reviews'
    __table_args__ = (UniqueConstraint('attempt_id', 'task_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('bank_attempts.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(80))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    score: Mapped[int]
    feedback: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
