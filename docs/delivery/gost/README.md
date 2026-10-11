# Письменный комплект

Семь документов доступны в PDF и Word. Чёрный текст, А4, поля 30/15/20/20 мм,
основной текст 14 пт, полуторный интервал; рисунки и таблицы имеют номера,
подписи и источники. Применимые правила ГОСТ и границы заявления —
[описание оформления](../../55-document-formatting.md).

| Документ | PDF | Word |
|---|---|---|
| Самостоятельное развёртывание | [PDF](self-deployment-guide.pdf) | [DOCX](self-deployment-guide.docx) |
| Руководство выпуска | [PDF](release-guide.pdf) | [DOCX](release-guide.docx) |
| Справочник API | [PDF](api-guide.pdf) | [DOCX](api-guide.docx) |
| Сопроводительная документация | [PDF](documentation.pdf) | [DOCX](documentation.docx) |
| Технический отчёт | [PDF](technical-report.pdf) | [DOCX](technical-report.docx) |
| Проектный отчёт | [PDF](project-report.pdf) | [DOCX](project-report.docx) |
| Актуальный комплект документации | [PDF](all-documents.pdf) | [DOCX](all-documents.docx) |

[ZIP](../fsp-documents-gost.zip) содержит документы, 19 исходных Markdown,
manifest, иллюстрации и копии лицензий. Состав задан явно в
[document-set.json](../../document-set.json); этапные планы и внутренние
рабочие заметки в сборник не включаются.

## Повторная сборка

Из корня проекта с Docker и Bash:

```bash
./scripts/run.sh report
```

Команда собирает tools-контейнер, PDF/Word, проверяет оформление и формирует ZIP.
Для проверки фактической нумерации Word нужен отдельный рендер в LibreOffice
или Word: XML-проверка сама по себе не подтверждает вид страниц.
Команды приложения остаются копируемым текстом в Markdown и Word.
