"""Лёгкий локальный запуск без Docker, PostgreSQL и VM-раннера (SQLite, синтетические данные).

    cd web && npm ci && npm run build && cd ..
    python scripts/dev_local.py [--host 127.0.0.1] [--port 8470] [--db .local/dev.sqlite] [--live]

Режим --live работает как обычный сайт: демо-вход отключён, участник и работодатель
регистрируются сами (адрес name@example.invalid, код подтверждения приходит в раздел
«Почта» самого стенда), вводят свои данные и проходят весь путь. Для двух ролей откройте
два разных браузера или профиля (сессия хранится в cookie). Готовые демо-кандидаты
остаются в банке, чтобы работодателю было из кого выбирать. База — отдельный файл
.local/live.sqlite; удалите её, чтобы начать с чистого листа.

Практические задания с исполнением кода в этом режиме недоступны (нужен Docker-раннер);
весь основной путь (регистрация, тест, подбор, приглашение, контакт) работает.
Только для локальной демонстрации на синтетических данных.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8470)
    parser.add_argument('--host', default='127.0.0.1', help='адрес прослушивания; 0.0.0.0 — только внутри изолированной Docker-сети')
    parser.add_argument('--db', type=Path, default=None)
    parser.add_argument('--live', action='store_true', help='как настоящий сайт: без демо-входа, регистрация и ввод своих данных')
    args = parser.parse_args()
    if args.live:
        os.environ['FSP_DEMO_LOGIN'] = '0'
    args.db = args.db or ROOT / '.local' / ('live.sqlite' if args.live else 'dev.sqlite')
    os.environ.setdefault('FSP_SQLITE_POOL', '1')   # параллельные запросы браузера: пул соединений и WAL
    import uvicorn
    from src.server.app import create_app
    from src.server.models import Base
    import src.server.bank_models  # noqa: F401  регистрация таблиц банков заданий
    args.db.parent.mkdir(parents=True, exist_ok=True)
    app = create_app('sqlite:///' + args.db.as_posix(), demo=True)
    Base.metadata.create_all(app.state.engine)
    if not (ROOT / 'web' / 'dist').is_dir():
        print('Интерфейс не собран: выполните «cd web && npm ci && npm run build». API доступен на /api/docs.')
    print(('Живой режим' if args.live else 'Демо-режим') + f': http://127.0.0.1:{args.port}/ (база {args.db})', flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
