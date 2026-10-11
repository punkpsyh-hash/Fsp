"""Сообщения компании и кандидата.

Диалог открывается только после того, как контакт разрешён: кандидат принял приглашение или
сам откликнулся (та же проверка, что открывает контактные данные). После отзыва контакта
писать нельзя, прежняя переписка остаётся читаемой для обеих сторон. Сообщения — обычный
текст без разметки и вложений; стенд синтетический, внешней доставки нет.
Чтение не меняет данные: пометка «прочитано» выполняется отдельным запросом.
"""
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from .models import Application, ChatMessage, Company, Offer, Profile, User, now
from .schemas import Input

HOURLY_LIMIT = 20
MAX_BODY = 2000
ACTIVE_APPLICATION = ['sent', 'viewed', 'accepted']


class ChatMessageInput(Input):
    body: str = Field(min_length=1, max_length=MAX_BODY)

    @field_validator('body')
    @classmethod
    def plain_text(cls, value):
        text = value.strip()
        if not text:
            raise ValueError('Сообщение не может быть пустым')
        if any(ord(char) < 32 and char not in '\n\t' for char in text):
            raise ValueError('Служебные символы в сообщении запрещены')
        return text


class ChatMessageView(BaseModel):
    id: str
    sender_role: str
    body: str
    created_at: datetime
    read: bool
    mine: bool


class ChatThreadView(BaseModel):
    counterpart_id: str
    counterpart_name: str
    can_send: bool
    unread: int
    last_body: str | None = None
    last_at: datetime | None = None
    last_sender_role: str | None = None


class ReadResult(BaseModel):
    marked: int


def attach_messaging(app, db_session, candidate, employer, permitted_contact, profile_alias, audit):
    def pair(user, other_id):
        """(company_id, candidate_id) для текущей стороны."""
        return (user.id, other_id) if user.role == 'employer' else (other_id, user.id)

    def has_history(db, company_id, candidate_id):
        return db.scalar(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.company_id == company_id, ChatMessage.candidate_id == candidate_id)) > 0

    def counterpart_name(db, user, other_id):
        if user.role == 'employer':
            profile = db.get(Profile, other_id)
            return 'Кандидат ' + profile_alias(profile) if profile else 'Кандидат'
        company = db.get(Company, other_id)
        other = db.get(User, other_id)
        return company.name if company else (other.label if other else 'Компания')

    def check_thread(db, user, other_id):
        """Собеседник должен существовать с нужной ролью; чужой диалог неотличим от несуществующего."""
        other = db.get(User, other_id)
        if not other or other.role != ('candidate' if user.role == 'employer' else 'employer'):
            raise HTTPException(404, 'Диалог не найден')
        company_id, candidate_id = pair(user, other_id)
        allowed = permitted_contact(db, company_id, candidate_id)
        if not allowed and not has_history(db, company_id, candidate_id):
            raise HTTPException(404, 'Диалог не найден')
        return company_id, candidate_id, bool(allowed)

    def message_view(m, user):
        mine = m.sender_role == ('company' if user.role == 'employer' else 'candidate')
        return ChatMessageView(id=m.id, sender_role=m.sender_role, body=m.body, created_at=m.created_at,
                               read=m.read_at is not None, mine=mine)

    def counterparts(db, user):
        """Собеседники с историей либо с открытым контактом."""
        if user.role == 'employer':
            mine_col, other_col = ChatMessage.company_id, ChatMessage.candidate_id
            offers = select(Offer.candidate_id).where(Offer.company_id == user.id, Offer.status == 'accepted',
                                                      Offer.contact_revoked.is_(False))
            applications = select(Application.candidate_id).where(
                Application.company_id == user.id, Application.status.in_(ACTIVE_APPLICATION),
                Application.contact_revoked.is_(False))
        else:
            mine_col, other_col = ChatMessage.candidate_id, ChatMessage.company_id
            offers = select(Offer.company_id).where(Offer.candidate_id == user.id, Offer.status == 'accepted',
                                                    Offer.contact_revoked.is_(False))
            applications = select(Application.company_id).where(
                Application.candidate_id == user.id, Application.status.in_(ACTIVE_APPLICATION),
                Application.contact_revoked.is_(False))
        found = set(db.scalars(select(other_col).where(mine_col == user.id).distinct()))
        return found | set(db.scalars(offers)) | set(db.scalars(applications))

    def threads(db, user):
        sender_other = 'candidate' if user.role == 'employer' else 'company'
        result = []
        for other_id in counterparts(db, user):
            company_id, candidate_id = pair(user, other_id)
            allowed = permitted_contact(db, company_id, candidate_id)
            last = db.scalar(select(ChatMessage).where(
                ChatMessage.company_id == company_id, ChatMessage.candidate_id == candidate_id
            ).order_by(ChatMessage.created_at.desc()).limit(1))
            if not allowed and not last:
                continue
            unread = db.scalar(select(func.count()).select_from(ChatMessage).where(
                ChatMessage.company_id == company_id, ChatMessage.candidate_id == candidate_id,
                ChatMessage.sender_role == sender_other, ChatMessage.read_at.is_(None)))
            result.append(ChatThreadView(
                counterpart_id=other_id, counterpart_name=counterpart_name(db, user, other_id),
                can_send=bool(allowed), unread=unread, last_body=last.body[:160] if last else None,
                last_at=last.created_at if last else None, last_sender_role=last.sender_role if last else None))
        result.sort(key=lambda t: (t.last_at is None, -(t.last_at.timestamp() if t.last_at else 0)))
        return result

    def listing(db, user, other_id, limit):
        company_id, candidate_id, _ = check_thread(db, user, other_id)
        rows = db.scalars(select(ChatMessage).where(
            ChatMessage.company_id == company_id, ChatMessage.candidate_id == candidate_id
        ).order_by(ChatMessage.created_at.desc()).limit(limit)).all()
        return [message_view(m, user) for m in reversed(rows)]

    def send(db, user, other_id, body):
        company_id, candidate_id, allowed = check_thread(db, user, other_id)
        if not allowed:
            raise HTTPException(403, 'Контакт не открыт или отозван: отправка сообщений недоступна')
        role = 'company' if user.role == 'employer' else 'candidate'
        recent = db.scalar(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.company_id == company_id, ChatMessage.candidate_id == candidate_id,
            ChatMessage.sender_role == role, ChatMessage.created_at > now() - timedelta(hours=1)))
        if recent >= HOURLY_LIMIT:
            raise HTTPException(429, 'Слишком много сообщений: не более %d в час' % HOURLY_LIMIT)
        message = ChatMessage(company_id=company_id, candidate_id=candidate_id, sender_role=role, body=body)
        db.add(message)
        db.flush()
        audit(db, user, 'chat.message', message.id)
        db.commit()
        return message_view(message, user)

    def mark_read(db, user, other_id):
        company_id, candidate_id, _ = check_thread(db, user, other_id)
        sender_other = 'candidate' if user.role == 'employer' else 'company'
        rows = db.scalars(select(ChatMessage).where(
            ChatMessage.company_id == company_id, ChatMessage.candidate_id == candidate_id,
            ChatMessage.sender_role == sender_other, ChatMessage.read_at.is_(None)).with_for_update()).all()
        for row in rows:
            row.read_at = now()
        db.commit()
        return ReadResult(marked=len(rows))

    @app.get('/api/v1/company/chats', response_model=list[ChatThreadView], tags=['Сообщения'])
    def company_threads(user=Depends(employer), db=Depends(db_session)):
        return threads(db, user)

    @app.get('/api/v1/company/chats/{candidate_id}/messages', response_model=list[ChatMessageView], tags=['Сообщения'])
    def company_messages(candidate_id: str, limit: int = 100, user=Depends(employer), db=Depends(db_session)):
        return listing(db, user, candidate_id, max(1, min(limit, 200)))

    @app.post('/api/v1/company/chats/{candidate_id}/messages', status_code=201, response_model=ChatMessageView, tags=['Сообщения'])
    def company_send(candidate_id: str, body: ChatMessageInput, user=Depends(employer), db=Depends(db_session)):
        return send(db, user, candidate_id, body.body)

    @app.post('/api/v1/company/chats/{candidate_id}/read', response_model=ReadResult, tags=['Сообщения'])
    def company_read(candidate_id: str, user=Depends(employer), db=Depends(db_session)):
        return mark_read(db, user, candidate_id)

    @app.get('/api/v1/candidate/chats', response_model=list[ChatThreadView], tags=['Сообщения'])
    def candidate_threads(user=Depends(candidate), db=Depends(db_session)):
        return threads(db, user)

    @app.get('/api/v1/candidate/chats/{company_id}/messages', response_model=list[ChatMessageView], tags=['Сообщения'])
    def candidate_messages(company_id: str, limit: int = 100, user=Depends(candidate), db=Depends(db_session)):
        return listing(db, user, company_id, max(1, min(limit, 200)))

    @app.post('/api/v1/candidate/chats/{company_id}/messages', status_code=201, response_model=ChatMessageView, tags=['Сообщения'])
    def candidate_send(company_id: str, body: ChatMessageInput, user=Depends(candidate), db=Depends(db_session)):
        return send(db, user, company_id, body.body)

    @app.post('/api/v1/candidate/chats/{company_id}/read', response_model=ReadResult, tags=['Сообщения'])
    def candidate_read(company_id: str, user=Depends(candidate), db=Depends(db_session)):
        return mark_read(db, user, company_id)
