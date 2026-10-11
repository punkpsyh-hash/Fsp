# Независимая security-проверка индивидуальной регистрации жюри

Дата: 2026-10-11
Режим: только чтение; проект, Git и runtime не изменялись и не развёртывались.

## Итог

Security gate по проверенному коду и конфигурации: **пройден**. В финальном diff не осталось подтверждённых уязвимостей или иных блокирующих дефектов в заявленном контуре индивидуальной регистрации.

## Проверенный контур

- `src/server/app.py`, `src/server/jury.py`, `src/server/schemas.py`, `src/server/security.py`;
- `web/src/main.tsx`;
- `tests/test_jury_individual_registration.py` и связанные тесты изоляции банков;
- `compose.jury-individual.yaml`, `Dockerfile`;
- `scripts/jury-relay-nas.sh` и относящаяся документация запуска.

Проверены: регистрация без сессии и Origin/CSRF-модель, ограничение ёмкости и конкурентный доступ к rate-limit ledger, стоимость PBKDF2, отзыв seed-сессий, изоляция candidate/employer и банков, повторный startup после допустимого редактирования профиля, строгая схема запроса, фактический алгоритм и параметры хеширования пароля.

## Исправленные в ходе проверки дефекты

1. `scripts/jury-relay-nas.sh:30-40` теперь выбирает пятифайловый Compose-набор при `FSP_JURY_INDIVIDUAL_REGISTRATION=1`, закрытый набор при `0`/пустом значении и отклоняет иное значение. Ранее публичный запуск мог остаться в старом общем-password режиме.
2. `scripts/jury-relay-nas.sh:114-121` требует `gate` до `validate`/`up` в индивидуальном режиме. Это устраняет обход публичного gate через `prepare`.
3. `src/server/app.py:127-158` отклоняет чужой `Origin` до изменения rate-limit ledger. Подтверждённый прежний сценарий `rate=1: foreign 403 -> allowed 429` закрыт; регрессия ожидает `foreign 403 -> allowed 201`.
4. `src/server/app.py:51-71,114-115` ограничивает обе таблицы rate-limit значением 1024 ключа через bounded `OrderedDict`; устранён рост памяти на уникальных IP.

## Подтверждённые свойства

- Регистрация выключена по умолчанию и возвращает 404 вне opt-in; поддерживаются только роли `candidate`/`employer`, пароль 12–128 символов, `consent=true`, дополнительные поля запрещены.
- Идентификатор создаётся из `secrets.token_hex(16)` (128 бит); служебный адрес использует домен `.invalid`; пользователь не вводит email или ФИО.
- PBKDF2-HMAC-SHA256 реально использует 600000 итераций, случайную 16-байтовую соль и 32-байтовый digest. Startup принимает только PBKDF2-SHA256 с 600000–2000000 итераций и ожидаемой формой соли/digest.
- В индивидуальном режиме seed-пароли очищаются, seed-сессии удаляются; startup отклоняет посторонних обычных пользователей, сохраняя валидные индивидуальные хеши.
- Ограничения 5 регистраций/час/IP и 10 password-auth/мин/IP применяются до дорогого password hash; bounded ledger защищён lock. Compose закрепляет один Uvicorn worker, что соответствует in-memory модели лимитера.
- Candidate/employer dependencies и owner-фильтры изолируют данные. `platform` bank scope разрешён только служебному seed employer, вход которого в индивидуальном режиме закрыт; публичные DTO не раскрывают скрытые эталоны.
- Startup не зависит от изменяемых label/contact/profile/resume полей сверх необходимых структурных инвариантов; проверен regression с изменённым employer-профилем.
- Существующий локальный email-verification flow сохранён вне jury mode.

## Верификация

- Лично выполнено в свежем read-only Docker: `tests/test_jury_individual_registration.py` — **23 passed**, одно предупреждение совместимости Starlette/httpx.
- Лично выполнено: `bash -n scripts/jury-relay-nas.sh` после финальной правки — exit 0.
- Лично проверен resolved Compose с безопасными placeholder-переменными: individual=1, max=200, registration=5, auth=10; app/db не публикуют порты, edge опубликован только на `127.0.0.1:18083`, используется публичный Caddyfile.
- Лично измерен один локальный sample PBKDF2 в текущем контейнере: hash около 0.088 с, verify около 0.081 с. Это проверка фактического алгоритма, не нагрузочный SLA.
- Координатор сообщил о финальном isolated frontend build и fake-Docker CLI-наборе **6 passed**, включая ветки выбора Compose и обязательный gate в `prepare`; это отмечено как внешнее для данного reviewer-процесса свидетельство.

Полные SQLite/PostgreSQL, browser и live relay/proxy проверки выполняет координатор перед публичным запуском; данный вывод относится к security gate проверенного source/config diff.

## Дополнение после фактической NAS-валидации

После первого gate координатор обнаружил, что закреплённый Caddy binary имеет file capability `NET_BIND_SERVICE`: запуск validator с одним `--cap-drop ALL` завершался `exec EPERM`. Финальная строка `scripts/jury-relay-nas.sh:90` сохраняет `--network none`, `--cap-drop ALL` и `no-new-privileges`, добавляя обратно только `--cap-add NET_BIND_SERVICE`. Это минимальная capability, необходимая для исполнения данного pinned binary; сетевой доступ validator по-прежнему отсутствует. Новых security-дефектов правка не создаёт, итоговый gate остаётся пройденным.

- Лично просмотрен однострочный diff и повторно выполнен `bash -n` в read-only/network-none Docker: exit 0.
- `tests/test_jury_relay_commands.py:70-71` фиксирует наличие `--cap-drop ALL` и единственной добавленной `NET_BIND_SERVICE`.
- Координатор сообщил: фактический pinned-Caddy validate на NAS завершился `Valid configuration`; fake-Docker relay CLI-набор — **6 passed за 0.70 с**. Эти два результата являются свидетельством координатора, а не лично выполненным NAS-прогоном reviewer-процесса.
- Координатор также сообщил о завершённых наборах SQLite **565/5/6** и auth **141/3**; PostgreSQL-проверка на момент дополнения продолжалась.
