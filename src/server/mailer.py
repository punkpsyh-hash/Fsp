"""SMTP-адаптер. По умолчанию локальный mail sink в БД; наружу ничего не отправляется.
SMTP включается только явной локальной конфигурацией. Пароль — переменная окружения.
"""
from email.message import EmailMessage
import os
import smtplib
import ssl

from .schemas import Email


def smtp_configuration():
    """Явное включение транспорта; не подтверждение юридической допустимости."""
    host = os.environ.get('FSP_SMTP_HOST', '').strip()
    enabled = os.environ.get('FSP_SMTP_ENABLED', '0')
    if enabled not in {'0', '1'}:
        raise ValueError('FSP_SMTP_ENABLED должен быть 0 или 1')
    if host and enabled != '1':
        raise ValueError('Внешняя почта выключена: для проверенного SMTP явно задайте FSP_SMTP_ENABLED=1')
    if enabled == '1' and not host:
        raise ValueError('Для SMTP требуется FSP_SMTP_HOST')
    if not host:
        return None
    mode = os.environ.get('FSP_SMTP_TLS', 'starttls')
    if mode not in {'starttls', 'ssl'}:
        raise ValueError('SMTP требует TLS')
    try:
        port = int(os.environ.get('FSP_SMTP_PORT', '465' if mode == 'ssl' else '587'))
    except ValueError as error:
        raise ValueError('Некорректный порт SMTP') from error
    if not 1 <= port <= 65535:
        raise ValueError('Некорректный порт SMTP')
    return host, port, mode


def send_link(email, token):
    # Ограничение синтетического стенда действует и при прямом вызове адаптера.
    recipient = Email(email=email).email
    configuration = smtp_configuration()
    if configuration is None:
        return 'local-mailbox'
    host, port, mode = configuration
    message=EmailMessage()
    message['From']=os.environ.get('FSP_SMTP_FROM','fsp@example.invalid')
    message['To']=recipient
    message['Subject']='ФСП · подтверждение тестового адреса'
    message.set_content('Локальный синтетический стенд. Одноразовый код подтверждения действует 30 минут:\n'+token+'\nНе пересылайте этот код. Реальные персональные данные не используйте.')
    context=ssl.create_default_context()
    connection=smtplib.SMTP_SSL(host,port,timeout=10,context=context) if mode=='ssl' else smtplib.SMTP(host,port,timeout=10)
    with connection as smtp:
        if mode=='starttls':smtp.starttls(context=context)
        username=os.environ.get('FSP_SMTP_USER')
        if username:smtp.login(username,os.environ.get('FSP_SMTP_PASSWORD',''))
        smtp.send_message(message)
    return 'smtp'
