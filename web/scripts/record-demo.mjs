// Запись только локального стенда. Новый синтетический аккаунт, без удаления данных.
import { chromium, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, rename } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { scenarioAnswer } from "./scenario-oracle.mjs";

async function questionTitle(page) {
  const prompt = (await page.locator("fieldset legend").innerText()).replace(/^\d+\.\s*/, "");
  const code = page.locator(".assessment-question .code-sample");
  if (!(await code.count())) return prompt;
  return `${(await code.first().innerText()).replace(/\n+$/, "")}\n${prompt}`;
}
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const out = path.join(root, "docs/delivery");
const temporary =
  process.env.FSP_RECORDING_DIR ||
  path.join(root, "web/test-results/demo-recording");
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, slowMo: 100 });
const context = await browser.newContext({
  baseURL: "http://127.0.0.1:8470",
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: temporary, size: { width: 1280, height: 800 } },
});
const page = await context.newPage();
const video = page.video();
const email = "demo-video-" + Date.now() + "@example.invalid";
const password = randomUUID();
const marker = "Предложение для видеодемонстрации " + Date.now();
const pause = () => page.waitForTimeout(1200);
async function screenshotBlock(block, name) {
  await block.scrollIntoViewIfNeeded();
  await pause();
  await block.screenshot({ path: path.join(out, `${name}-desktop.png`) });
  await page.setViewportSize({ width: 320, height: 800 });
  await block.scrollIntoViewIfNeeded();
  await pause();
  await block.screenshot({ path: path.join(out, `${name}-mobile.png`) });
  await page.setViewportSize({ width: 1280, height: 800 });
}
const tab = async (name) => {
  await page.getByRole("button", { name, exact: true }).click();
  await pause();
};
async function revealPagedRow(label, row) {
  const pages = page.getByRole("navigation", { name: `Страницы: ${label}` });
  await expect(pages).toBeVisible();
  for (let step = 0; step < 32 && !(await row.count()); step++) {
    const next = pages.getByRole("button", { name: /Следующая страница/ });
    if (!(await next.isEnabled())) break;
    const current = await pages.getByRole("status").innerText();
    await next.click();
    await expect(pages.getByRole("status")).not.toHaveText(current);
  }
  await expect(row).toHaveCount(1);
  await row.scrollIntoViewIfNeeded();
}
async function juniorBackendAnswer(title) {
  const attempt = await (await page.request.get('/api/v1/candidate/active-assessment')).json();
  if (['scenarios-v5', 'scenarios-v6'].includes(attempt?.version)) {
    const normalize = value => value.replace(/\s+/g, ' ').trim();
    const question = attempt.questions.find(row => normalize(row.title) === normalize(title));
    if (!question) throw new Error('Видимый сценарий отсутствует в публичной форме');
    return scenarioAnswer(question, attempt.grade);
  }
  const range = title.match(/range\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (range) return String(Math.ceil(Math.max(0, Number(range[2]) - Number(range[1])) / Number(range[3])));
  const state = title.match(/Список xs = \[([^\]]+)\]/);
  const appended = title.match(/xs\.append\((\d+)\)/);
  if (state && appended)
    return String(state[1].split(",").map(Number).reduce((sum, value) => sum + value, Number(appended[1])));
  const count = title.match(/В таблице (\d+) строк, у (\d+) строк/);
  if (count) return String(Number(count[1]) - Number(count[2]));
  const join = title.match(/У (\d+) есть по (\d+) заказа/);
  if (join) return String(Number(join[1]) * Number(join[2]));
  const retry = title.match(/создаёт (\d+) разных операций POST/);
  if (retry) return retry[1];
  const access = title.match(/(\d+) компаний просматривают кандидата\. Кандидат разрешил контакт ровно (\d+) компаниям/);
  if (access) return String(Number(access[1]) - Number(access[2]));
  throw new Error(`Неизвестный синтетический вопрос: ${title}`);
}
async function candidateLogin() {
  await tab("Вход с паролем");
  await page.getByLabel("Демонстрационная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Войти с паролем", exact: true })
    .click();
  await expect(
    page.getByRole("navigation", { name: "Разделы кабинета" }),
  ).toBeVisible();
  await pause();
}
async function employerLogin() {
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await expect(
    page.getByRole("navigation", { name: "Разделы кабинета" }),
  ).toBeVisible();
  await pause();
}
try {
  await page.goto("http://127.0.0.1:8470");
  await page.locator(".showcase").screenshot({ path: path.join(out, "contest-showcase-desktop.png") });
  await pause();
  await page.getByLabel("Демонстрационная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page
    .getByLabel("Имя тестового профиля или команды")
    .fill("Синтетический кандидат для видео");
  await page.getByRole("checkbox", { name: /Согласен/ }).check();
  await page.getByRole("button", { name: "Создать тестовый аккаунт" }).click();
  const mail = page.locator(".mail-row").filter({ hasText: email });
  await mail.getByRole("button", { name: "Подтвердить вход" }).click();
  await pause();
  await page.getByLabel("Специализация", { exact: true }).selectOption("backend");
  await page.getByLabel("Ожидаемая зарплата от, руб./мес.").fill("135000");
  const declaredSkills = page.getByRole("group", { name: "Заявленные технологии", exact: true });
  await declaredSkills.getByRole("checkbox", { name: "FastAPI", exact: true }).check();
  await declaredSkills.getByRole("checkbox", { name: "Docker", exact: true }).check();
  await page.getByRole("button", { name: "Сохранить профиль" }).click();
  await expect(page.getByText(/Профиль сохранён/)).toBeVisible();
  await pause();
  await tab("Оценка");
  await page.getByRole("button", { name: "Начать оценку" }).click();
  const questionPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await expect(questionPages.getByRole("status")).toContainText("страница 1 из 12");
  await pause();
  for (let questionNumber = 1; questionNumber <= 12; questionNumber++) {
    const title = await questionTitle(page);
    await page.getByRole("radio", { name: await juniorBackendAnswer(title), exact: true }).check();
    await expect(page.getByText("Ответы сохранены на сервере", { exact: true })).toBeVisible();
    if (questionNumber < 12) {
      await questionPages.getByRole("button", { name: /Следующая страница/ }).click();
      await pause();
    }
  }
  await page.getByRole("button", { name: "Отправить ответы" }).click();
  const confirmation = page.getByRole("dialog", {
    name: "Проверка перед отправкой",
  });
  await expect(confirmation).toContainText("Отвечено 12 из 12. Без ответа: 0");
  await confirmation.getByRole("button", { name: "Подтвердить отправку" }).click();
  await expect(page.getByText("Оценочная форма пройдена")).toBeVisible();
  await expect(page.locator(".skill-report-row")).toHaveCount(3);
  await page.locator(".skill-report-list").screenshot({ path: path.join(out, "contest-feedback-desktop.png") });
  await pause();
  await tab("Профиль");
  const skillEvidence = page.locator(".skill-evidence");
  await expect(skillEvidence).toContainText("fastapi");
  await expect(skillEvidence).toContainText("docker");
  await expect(skillEvidence).toContainText("scenarios-v6");
  await expect(skillEvidence).toContainText("не повышает глобальный грейд");
  await screenshotBlock(skillEvidence, "skills-evidence");
  await tab("История");
  await tab("Приватность");
  await page.getByRole("button", { name: "Опубликовать профиль" }).click();
  await expect(
    page.getByRole("heading", { name: "Профиль опубликован" }),
  ).toBeVisible();
  await pause();
  const profile = await (
    await page.request.get("/api/v1/candidate/profile")
  ).json();
  const alias = profile.alias;
  await tab("Короткие задания");
  const task = page
    .locator(".record-row")
    .filter({ has: page.getByRole("button", { name: "Отправить подход" }) })
    .filter({ hasText: "Демо-команда X" })
    .first();
  await revealPagedRow("Доступные короткие задания", task);
  const taskTitle = await task.locator("h3").innerText();
  await task
    .getByLabel("Ваш подход")
    .fill(
      "Синтетический ответ: проверить владельца, две независимые компании, отсутствие доступа до согласия, отзыв и повторное действие.",
    );
  await task.getByRole("button", { name: "Отправить подход" }).click();
  await expect(
    page.getByText("Ответ передан компании", { exact: true }),
  ).toBeVisible();
  await pause();
  await tab("Вакансии");
  await tab("Выйти");
  await employerLogin();
  const workTasks = page.getByRole("group", { name: "Задачи команды", exact: true });
  await workTasks.getByRole("checkbox", { name: /^Разработка API/ }).check();
  await expect(workTasks).toContainText("Желательные навыки задач: python, http");
  await screenshotBlock(workTasks, "work-tasks");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page).toHaveURL(/work_tasks=api-development/);
  const row = page.locator(".candidate-row").filter({ hasText: alias });
  await revealPagedRow("Результаты подбора", row);
  await expect(row).toBeVisible();
  await row.scrollIntoViewIfNeeded();
  await pause();
  await row.getByRole("button", { name: "Сравнить", exact: true }).click();
  const availableRows = page.locator(".candidate-row");
  for (let index = 0; index < await availableRows.count(); index++) {
    const other = availableRows.nth(index);
    if ((await other.locator("h3").innerText()) !== alias) {
      await other.getByRole("button", { name: "Сравнить", exact: true }).click();
      break;
    }
  }
  const comparison = page.getByRole("region", { name: "Сравнение кандидатов", exact: true });
  await comparison.scrollIntoViewIfNeeded();
  await comparison.screenshot({ path: path.join(out, "contest-comparison-desktop.png") });
  await pause();
  await page.setViewportSize({ width: 320, height: 800 });
  await comparison.screenshot({ path: path.join(out, "contest-comparison-mobile.png") });
  await page.setViewportSize({ width: 1280, height: 800 });
  await row.getByRole("button", { name: "Пригласить", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Условия и задачи")
    .fill(
      marker +
        ". Python и PostgreSQL, удалённый формат, синтетические условия.",
    );
  await pause();
  await page.getByRole("button", { name: "Отправить предложение" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await tab("Отправленные");
  const sent = page.locator(".offer-row").filter({ hasText: marker });
  await expect(sent.getByText("Контакт кандидата скрыт")).toBeVisible();
  await pause();
  await tab("Задания");
  const response = page
    .locator(".record-row")
    .filter({ hasText: alias })
    .filter({ hasText: taskTitle });
  await revealPagedRow("Ответы кандидатов на задания", response);
  await expect(response).toBeVisible();
  await response.getByLabel("Балл компании, 0–100").fill("85");
  await response
    .getByLabel("Обратная связь", { exact: true })
    .fill(
      "Синтетическая обратная связь: названы владелец, отрицательные проверки и отзыв доступа.",
    );
  await response
    .getByRole("button", { name: "Сохранить оценку задачи" })
    .click();
  await expect(
    page.getByText("Обратная связь сохранена", { exact: true }),
  ).toBeVisible();
  await pause();
  await tab("Выйти");
  await candidateLogin();
  await tab("Короткие задания");
  await expect(page.getByText("Оценка компании: 85/100")).toBeVisible();
  await pause();
  await tab("Входящие");
  const incoming = page.locator(".offer-row").filter({ hasText: marker });
  await incoming.getByRole("button", { name: "Отметить просмотр" }).click();
  await expect(
    incoming.getByText("Просмотрено", { exact: true }),
  ).toBeVisible();
  await pause();
  await incoming
    .getByRole("button", { name: "Принять и открыть контакт" })
    .click();
  await expect(incoming.getByText("Принято", { exact: true })).toBeVisible();
  await pause();
  await tab("Выйти");
  await employerLogin();
  await tab("Отправленные");
  await expect(
    page
      .locator(".offer-row")
      .filter({ hasText: marker })
      .getByText(/Разрешённый контакт:/),
  ).toBeVisible();
  await pause();
  await tab("Выйти");
  await candidateLogin();
  await tab("Приватность");
  await page
    .locator(".mail-row")
    .filter({ hasText: "Демо-команда X" })
    .getByRole("button", { name: "Отозвать контакт" })
    .click();
  await expect(page.getByText("Доступ к контакту отозван")).toBeVisible();
  await pause();
  await page.screenshot({
    path: path.join(out, "candidate-privacy.png"),
    fullPage: true,
  });
  await tab("Выйти");
  await employerLogin();
  await tab("Отправленные");
  await expect(
    page
      .locator(".offer-row")
      .filter({ hasText: marker })
      .getByText("Контакт отозван кандидатом"),
  ).toBeVisible();
  await pause();
  await tab("Выйти");
  await candidateLogin();
  await tab("Вакансии");
  const vacancy = page
    .locator(".record-row")
    .filter({ hasText: "Backend-разработчик Python" })
    .first();
  await revealPagedRow("Открытые вакансии", vacancy);
  const vacancyTitle = await vacancy.locator("h3").innerText();
  await vacancy
    .getByRole("button", { name: "Откликнуться и разрешить контакт" })
    .click();
  await expect(
    page.getByText("Отклик отправлен. Контакт разрешён только этой компании", {
      exact: true,
    }),
  ).toBeVisible();
  await pause();
  await tab("Мои отклики");
  await expect(
    page
      .locator(".record-row")
      .filter({ hasText: vacancyTitle })
      .getByText(/Отправлен/),
  ).toBeVisible();
  await tab("Выйти");
  await employerLogin();
  await tab("Отклики");
  const application = page
    .locator(".record-row")
    .filter({ hasText: alias })
    .filter({ hasText: vacancyTitle });
  await revealPagedRow("Отклики на вакансии", application);
  await expect(application.getByText(/Разрешённый контакт:/)).toBeVisible();
  await pause();
  await tab("Выйти");
  await candidateLogin();
  await tab("Мои отклики");
  await page
    .locator(".record-row")
    .filter({ hasText: vacancyTitle })
    .getByRole("button", { name: "Отозвать отклик" })
    .click();
  await expect(page.getByText("Отклик отозван", { exact: true })).toBeVisible();
  await pause();
  await tab("Выйти");
  await employerLogin();
  await tab("Отклики");
  await expect(
    page
      .locator(".record-row")
      .filter({ hasText: alias })
      .filter({ hasText: vacancyTitle })
      .getByText("Контакт недоступен или отозван"),
  ).toBeVisible();
  await pause();
  await tab("Банк кандидатов");
  await page.screenshot({
    path: path.join(out, "employer-bank.png"),
    fullPage: true,
  });
  await pause();
  // Конструктор: набор создаётся через интерфейс, не через скрытый API.
  await tab("Конструктор заданий");
  const authoredTitle = "Конструктор: числовая практика " + Date.now();
  await page.getByLabel("Название нового набора").fill(authoredTitle);
  await page
    .getByRole("button", { name: "Создать набор", exact: true })
    .click();
  await page.getByLabel("Тип нового задания").selectOption("numeric");
  await page
    .getByRole("button", { name: "Добавить задание", exact: true })
    .click();
  await page
    .getByLabel("Название задания", { exact: true })
    .fill("Оценка результата");
  await page
    .getByLabel("Условие задания", { exact: true })
    .fill("Сколько будет 21 × 2? Укажите точное число.");
  await page
    .getByRole("listbox", { name: /^Проверяемые навыки/ })
    .selectOption("python");
  await page.getByLabel("Эталонное число", { exact: true }).fill("42");
  // Редактор сам сохраняет черновик через 1,5 с и отключает кнопку.
  await expect(
    page.getByText("Черновик сохранён на сервере", { exact: true }),
  ).toBeVisible();
  await tab("Предпросмотр кандидата");
  await page
    .getByRole("button", { name: "Опубликовать набор", exact: true })
    .click();
  await expect(
    page.getByText("Версия опубликована. Её задания и ключи неизменяемы", {
      exact: true,
    }),
  ).toBeVisible();
  await pause();
  // Готовые материалы проходят dry-run с явным подтверждением импорта.
  await page.getByRole("button", { name: "Все наборы", exact: true }).click();
  await tab("Импорт материалов");
  const importedTitle = "Практика кода: Python, JavaScript, SQL " + Date.now();
  const codeTask = (language, title, starter, input, output) => ({
    id: "demo-" + language,
    type: "code",
    title,
    prompt:
      language === "sql"
        ? "Выполните SELECT, возвращающий число 1. Результат — одна строка и одна колонка."
        : "Прочитайте число из stdin и выведите его без изменений.",
    skills: [language === "javascript" ? "javascript" : language],
    language,
    starter_code: starter,
    examples: [{ input, output, setup: "" }],
    hidden_tests: [
      {
        input: language === "sql" ? "" : "2",
        output: language === "sql" ? "[[1]]" : "2",
        setup: "",
      },
    ],
    runtime_limits: { wall_seconds: 3, memory_mb: 512 },
  });
  const importedDocument = {
    schema_version: "fsp-bank-v1",
    external_id: "video-" + Date.now(),
    scope: "employer",
    title: importedTitle,
    specialization: "backend",
    grade: "junior",
    time_limit_minutes: 60,
    tasks: [
      codeTask(
        "python",
        "Python: поток ввода",
        "# Напишите решение\n",
        "1",
        "1",
      ),
      codeTask(
        "javascript",
        "JavaScript: поток ввода",
        "// Напишите решение\n",
        "1",
        "1",
      ),
      codeTask(
        "sql",
        "SQL: первая выборка",
        "-- Напишите SELECT\n",
        "",
        "[[1]]",
      ),
    ],
  };
  await page
    .getByLabel("Файл готовых заданий", { exact: true })
    .setInputFiles({
      name: "practice.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(importedDocument)),
    });
  await page
    .getByRole("button", { name: "Проверить файл", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Можно сохранить черновик",
      exact: true,
    }),
  ).toBeVisible();
  await pause();
  await page
    .getByRole("button", { name: "Подтвердить импорт", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: importedTitle, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Опубликовать набор", exact: true })
    .click();
  await expect(
    page.getByText("Версия опубликована. Её задания и ключи неизменяемы", {
      exact: true,
    }),
  ).toBeVisible();
  await pause();
  await tab("Выйти");
  await candidateLogin();
  await tab("Практические наборы");
  const importedBank = page
    .locator(".record-row")
    .filter({
      has: page.getByRole("heading", { name: importedTitle, exact: true }),
    });
  await revealPagedRow("Доступные практические наборы", importedBank);
  await importedBank
    .getByRole("button", { name: "Пройти набор", exact: true })
    .click();
  const solutions = [
    "print(input())",
    "console.log(require('node:fs').readFileSync(0, 'utf8').trim())",
    "SELECT 1;",
  ];
  const taskTitles = [
    "Python: поток ввода",
    "JavaScript: поток ввода",
    "SQL: первая выборка",
  ];
  const practicePages = page.getByRole("navigation", {
    name: /^Страницы: Задания попытки/,
  });
  await expect(practicePages.getByRole("status")).toContainText("страница 1 из 3");
  for (let i = 0; i < solutions.length; i++) {
    if (i > 0) {
      await practicePages.getByRole("button", { name: /Следующая страница/ }).click();
      await expect(practicePages.getByRole("status")).toContainText(`страница ${i + 1} из 3`);
    }
    await page
      .getByLabel("Код решения: " + taskTitles[i], { exact: true })
      .fill(solutions[i]);
    await expect(
      page.getByText("Ответы сохранены на сервере", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", {
        name: "Запустить проверки: " + taskTitles[i],
        exact: true,
      })
      .click();
    await expect(
      page
        .locator(".code-feedback")
        .getByText(/Пройдено 1 из 1/),
    ).toBeVisible({ timeout: 250000 });
    await pause();
  }
  await page
    .getByRole("button", { name: "Завершить набор", exact: true })
    .click();
  const practiceFinish = page.getByRole("dialog", {
    name: "Проверьте ответы перед завершением",
  });
  await expect(practiceFinish).toContainText(/На сервере сохранено ответов: 3 из 3/);
  await practiceFinish.getByRole("button", { name: "Подтвердить завершение", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Результат набора", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".score")).toHaveText("100 / 100");
  await page.screenshot({
    path: path.join(out, "code-practice.png"),
    fullPage: true,
  });
  await pause();
  await tab("Профиль");
  await expect(skillEvidence).toContainText("практика работодателя");
  await expect(skillEvidence).toContainText("задач ≥50% / всего оценённых");
  await expect(skillEvidence).toContainText("не повышает глобальный грейд");
  await screenshotBlock(skillEvidence, "skills-evidence-practice");
  console.log("Сквозной сценарий пройден; сохранение записи и конвертация MP4.");
  await context.close();
  await video.saveAs(path.join(out, "demo.webm"));
  await browser.close();
  const mp4Temporary = path.join(out, ".demo-" + randomUUID() + ".mp4");
  execFileSync(
    "ffmpeg",
    [
      "-nostdin",
      "-y",
      "-i",
      path.join(out, "demo.webm"),
      "-c:v",
      "libx264",
      "-preset",
      "veryfast",
      "-threads",
      "2",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      mp4Temporary,
    ],
    { stdio: "ignore" },
  );
  await rename(mp4Temporary, path.join(out, "demo.mp4"));
  console.log(
    "Записаны docs/delivery/demo.webm и demo.mp4: регистрация, заявленные технологии, оценка и источники навыков, задачи команды и подбор, предложение, принятие и отзыв, вакансии, конструктор, импорт и исполнение Python/JavaScript/SQL, отдельные результаты практики.",
  );
} finally {
  if (browser.isConnected()) await browser.close();
}
