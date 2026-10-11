# 63. Доступ жюри к коду и материалам

Конкурсный выпуск [`punkpsyh-hash/Fsp`](https://github.com/punkpsyh-hash/Fsp)
публикуется с видимостью **Public**, основная ветка — `main`.
Для просмотра и скачивания аккаунт GitHub и приглашение не нужны.
Публикация разрешена владельцем 11 октября 2026 года.

## Скачать и запустить

1. Открыть [репозиторий](https://github.com/punkpsyh-hash/Fsp).
2. Скачать выпуск через **Code → Download ZIP** или клонировать его командой ниже.
3. Прочитать [инструкцию развёртывания](53-self-deployment.md).
4. Запустить `./scripts/run.sh start` из Bash. На Windows нужен Git Bash и Docker
   Desktop с Linux containers; Python и Node на хосте не требуются.

```bash
git clone --branch main --single-branch https://github.com/punkpsyh-hash/Fsp.git fsp
cd fsp
./scripts/run.sh start
./scripts/run.sh status
```

Целевой датированный комплект закрепляется тегом `lct-2026-jury-v3`. После его
публикации для точного воспроизведения выполните `git checkout lct-2026-jury-v3`.
Исходный ZIP доступен на [странице выпуска](https://github.com/punkpsyh-hash/Fsp/releases/tag/lct-2026-jury-v3).
До появления тега и протокола v3 эти ссылки являются целевыми. Тег
`lct-2026-jury-v2` остаётся неизменяемым историческим срезом.

## Материалы сдачи

- [Ссылки по полям формы конкурса](60-jury-submission.md).
- [Документация PDF](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026-jury-v3/documentation.pdf).
- [Презентация PowerPoint](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026-jury-v3/fsp-lct-2026.pptx).
- [Видео с пояснениями](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026-jury-v3/demo-explained.mp4).
- [Комплект PDF и Word](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026-jury-v3/fsp-documents-gost.zip).

Для проверки в браузере откройте [демо-стенд](https://fsptest.kolesnikovny.ru).
Внешний Basic Auth снят по решению владельца. В целевом v3 выберите роль,
задайте собственный пароль 12–128 символов, подтвердите его и согласие. Сайт
сразу выдаст синтетический логин `jury-…@example.invalid`: скопируйте и
сохраните его для входа после выхода. Общих логинов и пароля нет, письмо не
отправляется. Полный порядок — в [документе 60](60-jury-submission.md).
Видео и самостоятельный локальный запуск остаются резервом; пароли NAS, VPS
и базы данных для проверки не требуются.

Индивидуальный v3 уже активирован: внешний TLS health подтверждает 200/`ok`,
`jury-demo` и `auth_mode=individual`. Публикация тега и итоговый протокол ещё
готовятся; выбранный PostgreSQL-набор прошёл 76/76, live browser — шесть
потоков двух ролей в трёх движках, негативный HTTPS-набор — 10/10.

## История и условия использования

Публичный выпуск содержит очищенный снимок конкурсного решения. Полная
прежняя история сохраняется в закрытом `Fsp-private-history`; полный сторонний
брендбук, локальные данные, оригиналы с контактами и внутренние инструкции
не включаются в открытый выпуск. Старые номера коммитов в датированных
протоколах обозначают происхождение измерений, а не публичные версии кода.

Просмотр Public-репозитория не даёт права изменять основную ветку.
Приглашение коллабораторов нужно участникам разработки, а не проверяющим.
Общая лицензия проекта не выбрана; условия сторонних компонентов и конкурсных
материалов — в [реестре происхождения](59-copyright-and-components.md).

## Официальные источники GitHub

- [Клонирование репозитория](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository).
- [Скачивание архивов исходников](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives).
- [Переименование с сохранением истории](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).
