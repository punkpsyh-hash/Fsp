# 44. Развёртывание и эксплуатация

Инструкция относится к локальному конкурсному стенду. Публичный production-контур
не подготовлен: реальные персональные данные, реальные credentials ФСП и открытие
портов наружу не допускаются.

## 1. Требования

| Контур | Минимум | Примечание |
|---|---|---|
| Основной стенд | Docker Engine, Compose v2, 2 CPU, 4 ГБ RAM, 10 ГБ диска | Рекомендуются 4 CPU и 8 ГБ RAM |
| Практические задания | `/dev/kvm` | Без KVM `scripts/run.sh` автоматически добавляет медленный TCG overlay |
| Локальная модель | NVIDIA GPU от 6 ГБ VRAM, 12 ГБ RAM, NVIDIA Container Toolkit | Измерения выполнены на RTX 4070 Laptop 8 ГБ; нужен совместимый Linux-контейнерный GPU runtime |
| QLoRA | NVIDIA GPU от 8 ГБ VRAM, 40 ГБ свободного диска | Адаптеры v1/v2 не приняты в рабочую конфигурацию |

Все штатные компоненты, сборка, миграции и проверки запускаются через Docker.
Локальные Python и Node для стенда не требуются. Версии и измерения модели —
в [актуальное руководство](https://github.com/punkpsyh-hash/Fsp/blob/main/docs/45-ai-answer-check-and-training-package.md).

## 2. Первый запуск без модели

```bash
git clone https://github.com/punkpsyh-hash/Fsp.git fsp
cd fsp
git switch main
./scripts/run.sh start
./scripts/run.sh status
```

`start` создаёт `.env` со случайными локальными секретами, если файла ещё нет,
собирает образы и ждёт готовности `app` и `runner`. Существующий `.env` не
перезаписывается. Интерфейс: `http://127.0.0.1:8470`; API:
`http://127.0.0.1:8470/api/docs`.

Управление:

```bash
./scripts/run.sh logs       # последние 100 строк app и runner
./scripts/run.sh status
./scripts/run.sh stop       # сохраняет volume PostgreSQL
```

На Windows используйте Docker Desktop с Linux containers и Git Bash. Перед
командой с несколькими Compose-файлами:

```bash
export MSYS_NO_PATHCONV=1
export COMPOSE_PATH_SEPARATOR=:
```

Если `/dev/kvm` недоступен, runner работает через TCG. Это медленнее, но не
переносит выполнение пользовательского кода в API или обычный subprocess.

## 3. Локальная модель

### 3.1 Получение весов

Веса не входят в Git. `ml/fetch_model.py` загружает только файлы модели
`Qwen/Qwen3-4B-Instruct-2507` на закреплённом коммите
`cdbee75f17c01a7cc42f958dc650907174af0554` и сверяет SHA-256 каждого файла с
`ml/release/model-serving-v3-manifest.json`.

Через одноразовый контейнер Python:

```bash
image_digest='6c4dd321d176d61ea848dc8c73a4f7dbae8'
image_digest="${image_digest}f70e0ee48bb411ea2f045b599fa8e"
image_ref="python:3.12-slim@sha256:${image_digest}"
docker run --rm --network bridge \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD,dst=/workspace" \
  --workdir /workspace \
  "$image_ref" \
  python ml/fetch_model.py
```

Каталог назначения — `ml/models/qwen3-4b-instruct-2507-serving-v3/`; он исключён
из Git. Скрипт отклоняет изменённые и лишние файлы. Для загрузки требуется
около 8 ГБ и доступ к `huggingface.co`; сам сервис модели затем работает offline.

### 3.2 Linux с NVIDIA Container Toolkit

```bash
export FSP_LOCAL_MODEL_API_KEY="$(openssl rand -hex 24)"
COMPOSE_FILE=compose.yaml:compose.llm.yaml ./scripts/run.sh start
docker compose -f compose.yaml -f compose.llm.yaml ps
```

Модель должна перейти в `healthy`. Порт 8001 наружу не публикуется, сеть
`llm_net` внутренняя, веса подключены только для чтения. Генерация и подсказка
оценки остаются черновиками с обязательным решением человека. `app` начинает
работу с моделью только после обязательного warmup: это полный минимальный
inference по строгой схеме, а его ошибка не выдаётся за readiness. Модель
возвращает машинные причины `schema_rejected`, `generation_incomplete`,
`input_rejected` и `runtime_unavailable`; только `schema_rejected` допускает
один повтор генерации. Timeout, OOM и переполнение контекста не повторяются.

### 3.3 Windows с Docker Desktop

Сначала загрузите веса через `ml/fetch_model.py` по §3.1. Затем запустите
отдельный GPU-сервис:

```powershell
& .\scripts\run-local-model.ps1 start
& .\scripts\run-local-model.ps1 status
& .\scripts\run-local-model.ps1 stop
```

`start` собирает собственный образ `fsp-model` из `docker/model.Dockerfile`; при
первой сборке нужен доступ к индексам закреплённых Python/CUDA-зависимостей.
Интерпретатор и библиотеки берутся из этого образа, а manifest — из
`ml/release/model-serving-v3-manifest.json`; private сторонние образы и локальный
pilot-venv не требуются. Веса подключаются только для чтения, GPU-кэш хранится
на диске D, а API модели остаётся в закрытой Docker-сети.

Параметры API-контейнера и диагностика описаны в `ml/README.md`. Полный стек с
VM-runner на Windows использует TCG. Исторические GPU-измерения 10 октября
зафиксированы в docs/39. Docker Desktop был восстановлен после сбоя компонента
`dockerInference`; свежий результат относится только к полностью завершившемуся
прогону с новым протоколом.

Свежая ограниченная проверка 11 октября в проекте `fspgpu2`: после исправления
`f53c151` холодный запуск собственного образа довёл `model` и `app` до healthy.
LM Format Enforcer оказался несовместим с boolean `const` в минимальной схеме
прогрева, поэтому она заменена эквивалентной минимальной строковой enum-схемой.
Начальный результат 2/4 сохранён как диагностика до `e0a20e1`. С текущим образом
Windows helper достиг `ready` после загрузки и прогрева за 203,446 с. Финальный
живой прогон serving-v4 структурно принял 4/4 типа: single choice — 49,853 с,
multiple choice — 34,010 с, numeric — 17,458 с, open response — 82,748 с.
Ручная сверка подтвердила ключи трёх закрытых заданий; в открытой рубрике есть
опечатка «идемрованности». Поэтому `review_required` и редактура человеком остаются
обязательными. Локальный отчёт: `протокол генерации` (архив этапа в закрытой истории).

### 3.4 Принятый приватный путь NAS → Windows GPU

В зафиксированном контуре приложение на NAS обращалось к Windows GPU-сервису
через приватный туннель и loopback-порты. Живой прогон выполнил четыре типа
генерации, публикацию банка, прохождение кандидатом и ручное решение автора;
отдельный UI smoke прошёл на ширинах 320, 768 и 1440. Восстановление туннеля
проверено отдельно. Доказательства — [приёмка выпуска](48-release-acceptance.md),
[NAS API](release/2026-10-11-completion/nas-live-api.json),
[NAS UI](release/2026-10-11-completion/nas-live-ui.json) и
[tunnel restart](release/2026-10-11-completion/tunnel-restart.json).

Эта приёмка относится к конкретным снимкам кода и среды. Она не открывает порт
модели публично и не подтверждает любой внешний OpenAI-совместимый сервер.
В ограниченном HTTPS-стенде жюри LLM выключен; его отдельные границы описаны в
[инструкции временного стенда](61-temporary-domain-stand.md).

## 4. Данные обучения

В Git находится воспроизводимый пакет `ml/release/`:

- `datasets/sft-v5.tar.gz`: train 7 552, val 314, heldout 1 615;
  SHA-256 `d64ab7a3bae7c3ab4fef82b0c303e89eb6e30820e21a8ba38d3d23893f4e807f`;
- manifest закреплённой базовой модели, manifests и отчёты адаптеров;
- код построения корпуса, обучения и оценки.

Адаптеры по 264 МБ хранятся вне Git на NAS:
`/Volume1/projects/Fsp-models/adapters/fsp-tasks-v1` и `fsp-tasks-v2`.
Они несовместимы с актуальным форматом вариантов и показали худший результат,
чем базовая модель. Рабочая конфигурация не подключает адаптер.

Корпус создан кодом с вычисленной истиной и не размечен независимыми экспертами.
Он не содержит персональных данных и не является доказательством калибровки.

## 5. Проверки

Для повторяемой приёмки рядом с работающим стендом используйте отдельный Compose
project без публикации портов:

```bash
COMPOSE_FILE=compose.yaml:compose.isolated.yaml ./scripts/run.sh verify
```

На Windows Git Bash добавьте переменные из §2. `verify` последовательно запускает
проверки SQLite/PostgreSQL и миграций, ranking/OpenAPI, smoke runner,
конкурсный банк и браузерные E2E. Команды для локализации ошибки:

```bash
./scripts/run.sh test
./scripts/run.sh test-postgres
./scripts/run.sh runner-test
./scripts/run.sh e2e
./scripts/run.sh contract
./scripts/run.sh api-check
```

Для адресного браузерного прогона `scripts/e2e_local.sh` всегда пересобирает
API/browser из текущего исходного кода и host `web/dist`, создаёт уникальные
сеть/контейнер и удаляет их через cleanup trap. Это защищает от ложного успеха
на старом Docker tag; успешная сборка helper сама по себе не заменяет полный E2E.

`contract`, evaluation и часть отчётов меняют отслеживаемые файлы. После них
проверьте `git diff`. Результат считается текущим только вместе с commit SHA,
датой, окружением и завершившейся командой.

Завершённые фазы повторной приёмки 11 октября:

| Фаза | Результат |
|---|---|
| SQLite | 378 passed, 1 skipped; 6 подтестов; 384,69 с |
| PostgreSQL 16 | 379 passed; 6 подтестов; 432,84 с |
| Runner TCG | 6/6 |
| API | 87 путей, 100 операций, 71 offline HTTP-пример, 34 JSON-тела по схемам |
| API PDF | 20 страниц, 100 строк операций, побайтная воспроизводимость |
| A11y | 9/9 axe-core в адресном Chromium-прогоне |
| Serving-v4 | 100 тестов SQLite за 19,07 с; 100 PostgreSQL за 17,73 с |
| Браузеры | Chromium 42/42 за 3,1 мин; Firefox 42/42 за 7,3 мин; WebKit 42/42 за 6,6 мин; всего 126/126 |
| GPU-генерация | 4/4 типов структурно приняты; Windows helper ready за 203,446 с |
| GPU-подсказка оценки | 16/16 валидных ответов, 0 ошибок; все четыре группы сохранили ожидаемый порядок и пороги |

Первый полный браузерный прогон выявил гонку ожидания списка в test helper.
После исправления `1cdb160` полный повтор прошёл 126/126: три отдельных
PostgreSQL/VM-стека, по одному worker для каждого движка, на образах с `e0a20e1`.
Живая GPU-проверка подсказки оценки также завершена: 16/16 валидных ответов,
0 ошибок; во всех четырёх группах strong > partial > wrong, strong ≥ 70,
wrong ≤ 30, а injection не поднялся выше wrong + 20. Техническая приёмка
закрыта по областям: полные SQL-наборы `e166c5a`, по 100 адресных тестов каждой
БД и браузерные образы `e0a20e1`, GPU-генерация 4/4 и review 16/16. Это
составной протокол, не один запуск и не экспертная калибровка. Итог и хеши —
[docs/48](48-release-acceptance.md) и
`verification-summary.json` (архив этапа в закрытой истории); GPU review —
`gpu-review-final.json` (архив этапа в закрытой истории). Для сравнения: историческая
приёмка 10 октября — 363 passed, 1 skipped на SQLite, 364 passed на PostgreSQL
и 126/126 E2E.

## 6. Резервная копия и восстановление

```bash
./scripts/run.sh backup
```

Команда создаёт custom-format `pg_dump` в `backups/`, который исключён из Git.
Проверяйте восстановление в отдельную пустую базу, не поверх рабочего volume:

```bash
docker compose exec -T db createdb -U fsp fsp_restore_check
docker compose exec -T db pg_restore -U fsp -d fsp_restore_check --exit-on-error \
  < backups/<имя-файла>.dump
docker compose exec -T db dropdb -U fsp fsp_restore_check
```

Удаление проверочной базы выполняйте только после успешного восстановления и
проверки выбранного имени. Автоматического переключения рабочей базы нет.

## 7. Обновление локального стенда

1. Создайте резервную копию.
2. Остановите процессы проверки и убедитесь, что рабочая копия чистая.
3. Выполните `./scripts/sync.sh pull`: скрипт разрешает только fast-forward и
   останавливается при расхождении истории.
4. Запустите `./scripts/run.sh start`. Миграции применяются при старте app.
5. Проверьте `status`, затем основной сценарий или полный `verify` в изолированном
   Compose project.

Не пересоздавайте `app`, пока `tools` или `browser` используют его network
namespace. Не подключайте Docker socket к API и не запускайте код заданий вне VM.

## 8. Границы эксплуатации

- Порты основного app и PostgreSQL привязаны к loopback. Публичный reverse proxy
  для полного контура не настраивается этой инструкцией; отдельный ограниченный
  HTTPS-стенд жюри описан в [docs/61](61-temporary-domain-stand.md).
- `.env`, dumps, веса, адаптеры, исходные XLSX/PDF и реальные данные остаются
  вне Git. Не выводите секреты в логи или отчёты.
- Реальной интеграции ФСП нет; mock нельзя представлять как внешний реестр.
- Принятый приватный канал NAS → Windows GPU относится к зафиксированной среде
  из §3.4; в jury-режиме модель выключена. Временная потеря маршрута 11 октября
  устранена. Core-коммит `e0a20e1d5c3e5797ae0614cf9a95bb696442560f`
  опубликован обычным push и подтверждён `git ls-remote`; чистая отдельная копия
  `/Volume1/projects/Fsp-llm-workspace` обновлена `git pull --ff-only` с `474f4f9`
  до `e0a20e1`. На этом этапе публикации runtime не разворачивался и не
  перезапускался, рабочая `/Volume1/projects/Fsp` на `main` не затрагивалась.
  Последующая живая приёмка приватного контура зафиксирована отдельно в §3.4;
  документация и артефакты выпуска публикуются завершающим коммитом ветки.
- GitHub CI/CD запрещён владельцем; `.github/workflows/` остаётся только на NAS
  и не входит в commit. Порядок публикации — [актуальное руководство](https://github.com/punkpsyh-hash/Fsp/blob/main/docs/63-jury-github-access.md).
