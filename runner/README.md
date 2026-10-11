# Исполнение кода в одноразовых VM

Этот worker не запускает исходный код задания в Linux контейнера. Для каждого
тестового случая он создаёт отдельную QEMU VM с собственным Linux kernel и
initramfs. Код Python/JavaScript и SQL выполняется только в гостевой машине.
У гостя нет сетевой карты, диска, host mounts, Docker socket, устройства KVM,
секретов broker, основной БД или файлов предыдущего случая. После результата
VM завершается; копия initramfs удаляется только из собственного временного
каталога worker. Изменяемые файлы гостя исчезают вместе с VM.

NAS использует KVM; CI или Linux x86_64 без KVM может явно выбрать
`FSP_RUNNER_ACCEL=tcg`. Автоматической смены ускорителя нет. Запуск worker
сначала проверяет реальную VM известной командой `print`, затем получает jobs.
Неудачный boot означает `system_error`, а не ошибку решения кандидата.

## Версии и границы

Базовые Python/Node образы закреплены digest в `docker/runner.Dockerfile`.
Гостевые версии: Python 3.12.13, Node 22.23.3, SQLite 3.46.1,
Linux 6.12.111+deb13-amd64. QEMU 10.0.13 Debian и kernel закреплены точными
версиями пакетов из подписанного Debian archive. Их транзитивные зависимости
управляются Debian; будущая замена package/digest требует новых проб.
`versions.json` и SHA-256 kernel/initramfs входят в фактический отчёт probe.
В рабочем образе `/opt/fsp-guest/licenses/` сохранены оригинальные notices
Node, Python, Linux, BusyBox, SQLite, glibc и QEMU, GPL-2/LGPL-2.1.
`versions.json` содержит guest package versions и официальные указатели
источников; `runtime-debian-packages.txt` — фактический receipt Debian runtime.
Это перечень происхождения компонентов, а не юридическое заключение.

SQLite — явно выбранный диалект учебных SQL заданий. Это не PostgreSQL 16:
PostgreSQL основной платформы не используется для выполнения SQL кандидата.
Гость создаёт отдельную in-memory БД из fixture, затем разрешает только SELECT.
Authorizer запрещает ATTACH/DETACH, PRAGMA, загрузку расширений и файловые
функции, изменение таблиц и несколько SQL statements. SQL ожидает JSON массив
строк в порядке выдачи; задача должна требовать ORDER BY, если порядок важен.

На случай: 1 vCPU, 512 MiB физической памяти VM; 2 секунды CPU по умолчанию
(серверный бюджет ограничен 1–3 при KVM), execution wall time CPU+2 s в госте и
CPU+4 s снаружи. Boot budget 15 s KVM / 90 s TCG отдельно от времени решения.
Максимум 16 процессов на UID, 32 FD, 64 KiB суммарного stdout/stderr,
64 MiB `/work`, файл не больше 64 KiB. Python/SQLite: address space 192 MiB;
Node: V8 heap 64 MiB, физический потолок VM 512 MiB. Огромный виртуальный
reservation V8 не ограничивается RLIMIT_AS. Эти бюджеты фиксированы runtime,
произвольная настройка RAM автором не применяется.

Явный software profile TCG умножает CPU budget на 10 (10–30 s), поскольку
Node startup на emulated CPU сам превышает двухсекундный бюджет. Это различие
указывается в `runtime_version` и probe отчёте. Оно не меняет память/сеть/VM
границу; TCG — медленный переносимый режим, результаты времени разных профилей
напрямую не сравниваются.

Worker выполняет последовательно не более 10 cases и имеет общий бюджет
240 s при KVM / 600 s при TCG (boot заметно медленнее). Compose дополнительно ограничивает worker memory/CPU/pids; основной
API и PostgreSQL получают отдельные контейнеры и не наследуют guest бюджеты.
Такой контур уменьшает риск; QEMU/KVM и ядра всё равно требуют обновлений,
а пробы не являются доказательством отсутствия всех возможных VM escapes.

## Broker protocol

У worker нет PostgreSQL credentials и прямого DB connection. Только
`FSP_RUNNER_BROKER_URL` и `FSP_RUNNER_TOKEN` длиной не менее 32 символов,
передаваемый в Authorization Bearer. Он не попадает в argv, VM или логи.

`POST /internal/runner/claim` с `{}` возвращает `{ "job": null }` либо:

```json
{
  "job": {
    "id": "server-generated-id",
    "lease_token": "temporary-opaque-lease",
    "language": "python",
    "source": "print(int(input()) * 2)",
    "time_limit_seconds": 2,
    "tests": [{ "stdin": "21\n", "setup": "", "expected": "42" }]
  }
}
```

Для SQL `expected` — массив массивов, `setup` — создание синтетических таблиц.
Ни один `expected`, ID или lease не помещается в VM. Сравнение выполняется
снаружи guest: Python/JS используют точную строку после `rstrip()`, SQL —
JSON rows. Код не может прочитать эталон как файл рядом с решением.

`POST /internal/runner/jobs/{id}/result`:

```json
{
  "lease_token": "temporary-opaque-lease",
  "status": "passed",
  "passed": 1,
  "total": 1,
  "duration_ms": 1000,
  "runtime_version": "Python 3.12.13; Linux 6.12.111+deb13-amd64; kvm"
}
```

Другие execution status: `wrong_answer`, `timeout`, `runtime_error`,
`system_error`; очередь дополнительно имеет `queued`/`running`.
`error_code` ограничен безопасной причиной. Отчёт не содержит stdout/stderr,
fixtures или решений; инфраструктурный сбой не считается провалом оценки.
API отвечает за атомарный claim, TTL 900 s, hash lease, повтор не более одного,
отказ просроченному worker и привязку оценки к source hash/version попытки.

## Проверки

```bash
./scripts/runner-probe.sh kvm  # полный набор реальных VM на NAS
./scripts/runner-probe.sh tcg  # явная software VM: три языка, wrong answer, timeout
```

Пробы используют отдельный контейнер без сети, портов и папок проекта,
не читают основной DB и не изменяют её. Сначала только известная benign команда
подтверждает boot; далее проверяются языки, oracle, timeout, лимиты памяти,
процессов и вывода, отсутствие host paths/секретов/сети, read-only runtime,
отсутствие изменений предыдущего job, SQL запреты и восстановление после ошибок.
Каждая строка — результат проверки, последняя — полный JSON отчёт с версиями,
SHA-256 и boot durations. Для сохранения отчёта у `runner.probe` есть
`--output /path/in/container/report.json` (каталог должен быть явно доступен).
Обёртка монтирует только собственный новый временный файл отчёта и после
успеха атомарно сохраняет `docs/runner-results-kvm.json` или
`docs/runner-results-tcg.json`; остальные документы ей не доступны.

Основания: [QEMU invocation](https://www.qemu.org/docs/master/system/qemu-manpage.html),
[Linux initramfs format](https://www.kernel.org/doc/html/latest/driver-api/early-userspace/buffer-format.html),
[Python resource](https://docs.python.org/3.12/library/resource.html),
[SQLite authorizer](https://www.sqlite.org/c3ref/set_authorizer.html).
