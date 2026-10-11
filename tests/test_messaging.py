"""Переписка компании и кандидата: доступ только при открытом контакте, приватность и лимиты."""
from tests.test_api import client, invite, login  # noqa: F401 - фикстура client


def open_contact(client):
    """Компания X приглашает кандидата A, кандидат принимает."""
    login(client, 'employer-x')
    offer = invite(client).json()
    login(client, 'candidate-a')
    assert client.post(f'/api/v1/candidate/invitations/{offer["id"]}/decision', json={'decision': 'accepted'}).status_code == 200
    return offer


def test_no_chat_before_acceptance(client):
    login(client, 'employer-x')
    invite(client)
    assert client.get('/api/v1/company/chats').json() == []
    assert client.get('/api/v1/company/chats/demo-candidate-a/messages').status_code == 404
    assert client.post('/api/v1/company/chats/demo-candidate-a/messages', json={'body': 'Здравствуйте'}).status_code == 404
    login(client, 'candidate-a')
    assert client.get('/api/v1/candidate/chats').json() == []
    assert client.post('/api/v1/candidate/chats/demo-employer-x/messages', json={'body': 'Привет'}).status_code == 404


def test_conversation_flow_unread_and_read_receipts(client):
    open_contact(client)
    login(client, 'employer-x')
    threads = client.get('/api/v1/company/chats').json()
    assert [t['counterpart_id'] for t in threads] == ['demo-candidate-a'] and threads[0]['can_send'] and threads[0]['unread'] == 0
    assert threads[0]['counterpart_name'].startswith('Кандидат P-')
    sent = client.post('/api/v1/company/chats/demo-candidate-a/messages', json={'body': '  Приглашаем на собеседование  '})
    assert sent.status_code == 201 and sent.json()['body'] == 'Приглашаем на собеседование' and sent.json()['mine'] is True

    login(client, 'candidate-a')
    thread = client.get('/api/v1/candidate/chats').json()[0]
    assert thread['counterpart_id'] == 'demo-employer-x' and thread['unread'] == 1
    messages = client.get('/api/v1/candidate/chats/demo-employer-x/messages').json()
    assert len(messages) == 1 and messages[0]['mine'] is False and messages[0]['read'] is False
    # Чтение не меняет данные: счётчик остаётся, пока явно не отмечено прочитанным.
    assert client.get('/api/v1/candidate/chats').json()[0]['unread'] == 1
    assert client.post('/api/v1/candidate/chats/demo-employer-x/read').json() == {'marked': 1}
    assert client.post('/api/v1/candidate/chats/demo-employer-x/read').json() == {'marked': 0}
    assert client.get('/api/v1/candidate/chats').json()[0]['unread'] == 0
    reply = client.post('/api/v1/candidate/chats/demo-employer-x/messages', json={'body': 'Спасибо, готов'})
    assert reply.status_code == 201

    login(client, 'employer-x')
    chat = client.get('/api/v1/company/chats/demo-candidate-a/messages').json()
    assert [m['sender_role'] for m in chat] == ['company', 'candidate']
    assert chat[0]['read'] is True and chat[1]['read'] is False and chat[1]['mine'] is False


def test_other_users_cannot_read_or_write(client):
    open_contact(client)
    login(client, 'employer-x')
    client.post('/api/v1/company/chats/demo-candidate-a/messages', json={'body': 'Закрытое сообщение'})
    login(client, 'employer-y')
    assert client.get('/api/v1/company/chats').json() == []
    assert client.get('/api/v1/company/chats/demo-candidate-a/messages').status_code == 404
    assert client.post('/api/v1/company/chats/demo-candidate-a/messages', json={'body': 'Я посторонний'}).status_code == 404
    login(client, 'candidate-b')
    assert client.get('/api/v1/candidate/chats').json() == []
    assert client.get('/api/v1/candidate/chats/demo-employer-x/messages').status_code == 404
    # Роль определяется маршрутом: кандидат не может открыть кабинет компании и наоборот.
    assert client.get('/api/v1/company/chats').status_code in {401, 403}
    login(client, 'employer-x')
    assert client.get('/api/v1/candidate/chats').status_code in {401, 403}
    # Собеседник должен быть пользователем нужной роли.
    assert client.get('/api/v1/company/chats/demo-employer-y/messages').status_code == 404


def test_revoked_contact_keeps_history_readable_but_blocks_sending(client):
    open_contact(client)
    login(client, 'employer-x')
    client.post('/api/v1/company/chats/demo-candidate-a/messages', json={'body': 'До отзыва'})
    login(client, 'candidate-a')
    assert client.delete('/api/v1/candidate/contacts/demo-employer-x').status_code == 204
    assert client.post('/api/v1/candidate/chats/demo-employer-x/messages', json={'body': 'После отзыва'}).status_code == 403
    thread = client.get('/api/v1/candidate/chats').json()[0]
    assert thread['can_send'] is False
    assert [m['body'] for m in client.get('/api/v1/candidate/chats/demo-employer-x/messages').json()] == ['До отзыва']
    login(client, 'employer-x')
    assert client.post('/api/v1/company/chats/demo-candidate-a/messages', json={'body': 'Ещё одно'}).status_code == 403
    assert len(client.get('/api/v1/company/chats/demo-candidate-a/messages').json()) == 1


def test_body_validation_and_rate_limit(client):
    open_contact(client)
    login(client, 'employer-x')
    path = '/api/v1/company/chats/demo-candidate-a/messages'
    for bad in ('', '   ', 'x' * 2001, 'a\x00b'):
        assert client.post(path, json={'body': bad}).status_code == 422
    assert client.post(path, json={'body': 'ok', 'extra': 1}).status_code == 422
    html = client.post(path, json={'body': '<b>жирный</b> текст'})
    assert html.status_code == 201 and html.json()['body'] == '<b>жирный</b> текст'  # хранится как текст
    for index in range(19):
        assert client.post(path, json={'body': f'Сообщение {index}'}).status_code == 201
    assert client.post(path, json={'body': 'Двадцать первое'}).status_code == 429
    # Лимит действует на отправителя, не на собеседника.
    login(client, 'candidate-a')
    assert client.post('/api/v1/candidate/chats/demo-employer-x/messages', json={'body': 'Ответ'}).status_code == 201
    assert len(client.get('/api/v1/candidate/chats/demo-employer-x/messages?limit=5').json()) == 5
