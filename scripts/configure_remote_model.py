"""Настроить только ключ удалённой модели и удержание, без вывода .env/секретов.

Выполняется через Docker в отдельной NAS-копии; stdin — локальный GPU key.env.
"""
import fcntl
import os
from pathlib import Path
import re
import secrets
import stat
import sys


def configure(path, key_line):
    path = Path(path)
    match = re.fullmatch(r'FSP_LOCAL_MODEL_API_KEY=([A-Za-z0-9_+/=-]{32,256})\s*', key_line)
    if not match:
        raise ValueError('Ожидается одна строка локального ключа модели; значение не выводится')
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        lines = stream.read().splitlines()
        if not any(line.startswith('FSP_DB_PASSWORD=') for line in lines):
            raise ValueError('Сначала выполните scripts/run.sh init в этой копии')
        values = {'FSP_LLM_API_KEY': match[1], 'FSP_INTEGRITY_ENFORCE': '1'}
        kept = [line for line in lines if line.split('=', 1)[0].strip() not in values]
        metadata = os.fstat(stream.fileno())
        temporary = path.with_name('.env.model-' + secrets.token_hex(8))
        try:
            target_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(target_fd, 'w') as target:
                os.fchmod(target.fileno(), stat.S_IMODE(metadata.st_mode))
                os.fchown(target.fileno(), metadata.st_uid, metadata.st_gid)
                target.write('\n'.join(kept + [key + '=' + value for key, value in values.items()]) + '\n')
                target.flush()
                os.fsync(target.fileno())
            current = path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise RuntimeError('Конфигурация заменена параллельно; повторите настройку')
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    key_line = sys.stdin.read(512)
    configure(root / '.env', key_line)
    # Проба получает только ключ модели, а не DB/runner/SMTP-настройки.
    client_path = root / 'local-data/model-tunnel/gpu-client.env'
    client_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = client_path.with_name('.gpu-client-' + secrets.token_hex(8))
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as target:
            target.write(key_line.strip().replace('FSP_LOCAL_MODEL_API_KEY=', 'FSP_LLM_API_KEY=', 1) + '\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, client_path)
    finally:
        temporary.unlink(missing_ok=True)
    print('Ключ модели и удержание настроены; остальные настройки сохранены')
