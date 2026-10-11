"""Создать локальную конфигурацию один раз, не раскрывая и не перезаписывая секреты."""
import os
import fcntl
from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1]/".env"
descriptor=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
with os.fdopen(descriptor,'r+') as stream:
    fcntl.flock(stream,fcntl.LOCK_EX)
    content=stream.read()
    keys={line.split('=',1)[0].strip() for line in content.splitlines() if '=' in line and not line.lstrip().startswith('#')}
    additions=[]
    if 'FSP_LOCAL_MODEL_API_KEY' in keys and not any(
            line.startswith('FSP_LOCAL_MODEL_API_KEY=') and line.split('=', 1)[1].strip()
            for line in content.splitlines()):
        raise SystemExit('FSP_LOCAL_MODEL_API_KEY пуст: удалите только эту строку и повторите init. Конфигурация сохранена.')
    if not content:
        additions=['FSP_DB_PASSWORD='+secrets.token_urlsafe(32),'FSP_DEMO_MODE=1']
    elif 'FSP_DB_PASSWORD' not in keys:
        raise SystemExit('В существующем .env отсутствует FSP_DB_PASSWORD. Существующая конфигурация сохранена.')
    if 'FSP_RUNNER_TOKEN' not in keys:
        additions.append('FSP_RUNNER_TOKEN='+secrets.token_urlsafe(48))
    if 'FSP_LOCAL_MODEL_API_KEY' not in keys:
        additions.append('FSP_LOCAL_MODEL_API_KEY='+secrets.token_urlsafe(48))
    if additions:
        stream.seek(0,os.SEEK_END)
        stream.write(('\n' if content and not content.endswith('\n') else '')+'\n'.join(additions)+'\n')
        stream.flush(); os.fsync(stream.fileno())
        print('Локальная конфигурация дополнена недостающими проектными ключами; прежние значения сохранены, секреты не выводятся')
    else:
        print('.env уже настроен; содержимое и права не изменены')
