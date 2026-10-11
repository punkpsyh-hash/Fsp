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

Датированный комплект закреплён тегом `lct-2026`. Для точного воспроизведения
после клонирования выполните `git checkout lct-2026`. Исходный ZIP того же
тега доступен на [странице выпуска](https://github.com/punkpsyh-hash/Fsp/releases/tag/lct-2026).

## Материалы сдачи

- [Ссылки по полям формы конкурса](60-jury-submission.md).
- [Документация PDF](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026/documentation.pdf).
- [Презентация PowerPoint](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026/fsp-lct-2026.pptx).
- [Видео с пояснениями](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026/demo-explained.mp4).
- [Комплект PDF и Word](https://github.com/punkpsyh-hash/Fsp/releases/download/lct-2026/fsp-documents-gost.zip).

Временный [HTTPS-стенд](https://fsptest.kolesnikovny.ru) сохраняет отдельный
парольный доступ жюри. Владелец передаёт пароль защищённым каналом; GitHub,
документы, видео и конкурсные слайды не содержат credentials.

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
