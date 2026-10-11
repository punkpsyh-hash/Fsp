import { test, expect, type Page } from "@playwright/test";

// Все проекты используют один loopback IP. Между браузерами выдерживаем окно
// ограничителя 30 auth-запросов/мин, сохраняя те же production-правила API.
test.beforeAll(async ({}, testInfo) => {
  if (testInfo.project.name !== "chromium") {
    testInfo.setTimeout(70000);
    await new Promise((resolve) => setTimeout(resolve, 61000));
  }
});

async function login(page: Page, name: string) {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(
    page.getByRole("navigation", { name: "Разделы кабинета" }),
  ).toBeVisible();
}

async function answerAndWaitForSave(page: Page, action: () => Promise<void>) {
  const saved = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/candidate/bank-attempts/") &&
      response.request().method() === "PATCH",
  );
  await action();
  expect((await saved).ok()).toBeTruthy();
  await expect(
    page.getByText("Ответы сохранены на сервере", { exact: true }),
  ).toBeVisible();
}

test("конструктор пяти типов, сохранение, прохождение, код и ручная проверка", async ({
  browser,
}, testInfo) => {
  test.setTimeout(360000);
  const authorContext = await browser.newContext(),
    candidateContext = await browser.newContext();
  const author = await authorContext.newPage(),
    candidate = await candidateContext.newPage();
  await candidate.emulateMedia({ reducedMotion: "reduce" });
  // Поздний ответ поиска старого экрана не должен стирать новый hash-маршрут.
  let releaseSearch!: () => void;
  let delayedSearch = false;
  const releasedSearch = new Promise<void>((resolve) => {
    releaseSearch = resolve;
  });
  await author.route("**/api/v1/company/searches", async (route) => {
    if (route.request().method() === "POST" && !delayedSearch) {
      delayedSearch = true;
      const response = await route.fetch();
      await releasedSearch;
      await route.fulfill({ response });
    } else await route.continue();
  });
  await login(author, "Демо-команда X");
  await author
    .getByRole("button", { name: "Конструктор заданий", exact: true })
    .click();
  releaseSearch();
  await expect(author.getByLabel("Название нового набора")).toBeVisible();
  await expect(author).toHaveURL(/#\/employer\/banks$/);
  const title = "Пять типов E2E " + Date.now();
  await author.getByLabel("Название нового набора").fill(title);
  await author
    .getByRole("button", { name: "Создать набор", exact: true })
    .click();
  await expect(author).toHaveURL(/#\/employer\/banks\//);
  const types = [
    "single_choice",
    "multiple_choice",
    "numeric",
    "open_response",
    "code",
  ];
  for (let i = 0; i < types.length; i++) {
    await author.getByLabel("Тип нового задания").selectOption(types[i]);
    await author
      .getByRole("button", { name: "Добавить задание", exact: true })
      .click();
    await author
      .getByLabel("Название задания", { exact: true })
      .fill("Задание " + (i + 1));
    await author
      .getByLabel("Условие задания", { exact: true })
      .fill(
        i === 4
          ? "Прочитайте число из stdin и выведите его без изменений."
          : "Синтетическое условие " + (i + 1),
      );
  }
  await author
    .getByRole("button", { name: "Сохранить черновик", exact: true })
    .click();
  await expect(
    author.getByText("Черновик сохранён на сервере", { exact: true }),
  ).toBeVisible();
  await author.reload();
  await expect(
    author.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  await author
    .getByRole("button", { name: "Предпросмотр кандидата", exact: true })
    .click();
  await expect(author.locator(".answer-task")).toHaveCount(5);
  await author
    .getByRole("button", { name: "Опубликовать набор", exact: true })
    .click();
  await expect(
    author.getByText("Версия опубликована. Её задания и ключи неизменяемы", {
      exact: true,
    }),
  ).toBeVisible();
  await login(candidate, "Кандидат А");
  await candidate
    .getByRole("button", { name: "Практические наборы", exact: true })
    .click();
  const row = candidate.locator(".record-row").filter({
    has: candidate.getByRole("heading", { name: title, exact: true }),
  });
  await row.getByRole("button", { name: "Пройти набор", exact: true }).click();
  const taskPages = candidate.getByRole("navigation", {
    name: /^Страницы: Задания попытки/,
  });
  await expect(taskPages.getByRole("status")).toContainText("страница 1 из 5");
  await expect(candidate.locator(".answer-task")).toHaveCount(1);
  await answerAndWaitForSave(candidate, async () => {
    await candidate
      .locator(".answer-task")
      .getByRole("radio", { name: "Вариант А", exact: true })
      .check();
  });
  await taskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(taskPages.getByRole("status")).toContainText("страница 2 из 5");
  await taskPages.getByRole("button", { name: /Предыдущая страница/ }).click();
  await expect(
    candidate.locator(".answer-task").getByRole("radio", { name: "Вариант А", exact: true }),
  ).toBeChecked();

  await taskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await answerAndWaitForSave(candidate, async () => {
    await candidate
      .locator(".answer-task")
      .getByRole("checkbox", { name: "Вариант А", exact: true })
      .check();
  });
  await answerAndWaitForSave(candidate, async () => {
    await candidate
      .locator(".answer-task")
      .getByRole("checkbox", { name: "Вариант Б", exact: true })
      .check();
  });
  await taskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await answerAndWaitForSave(candidate, async () => {
    await candidate.locator(".answer-task").getByLabel("Ваш числовой ответ", { exact: true }).fill("0");
  });
  await taskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await answerAndWaitForSave(candidate, async () => {
    await candidate.locator(".answer-task").getByLabel("Ваш ответ", { exact: true }).fill("Синтетический ответ с объяснением подхода и критериев.");
  });
  await taskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await answerAndWaitForSave(candidate, async () => {
    await candidate.locator(".answer-task").getByLabel("Код решения: Задание 5", { exact: true }).fill("print(input())");
  });
  await candidate.reload();
  const restoredTaskPages = candidate.getByRole("navigation", {
    name: /^Страницы: Задания попытки/,
  });
  await expect(restoredTaskPages.getByRole("status")).toContainText("страница 1 из 5");
  for (let taskNumber = 1; taskNumber < 4; taskNumber++)
    await restoredTaskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(restoredTaskPages.getByRole("status")).toContainText("страница 4 из 5");
  await expect(
    candidate.locator(".answer-task").getByLabel("Ваш ответ", { exact: true }),
  ).toHaveValue(/Синтетический ответ/);
  await restoredTaskPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(restoredTaskPages.getByRole("status")).toContainText("страница 5 из 5");
  await expect(
    candidate.locator(".answer-task").getByLabel("Код решения: Задание 5", { exact: true }),
  ).toHaveValue("print(input())");
  for (const width of [320, 375, 768, 1440]) {
    await candidate.setViewportSize({ width, height: 900 });
    expect(await candidate.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  const attemptId = new URL(candidate.url()).hash.split("/").at(-1)!;
  const projection = await (
    await candidate.request.get("/api/v1/candidate/bank-attempts/" + attemptId)
  ).json();
  for (const task of projection.version.tasks) {
    expect(task).not.toHaveProperty("answer_key");
    expect(task).not.toHaveProperty("hidden_tests");
    expect(task).not.toHaveProperty("numeric_answer");
  }
  await candidate
    .getByRole("button", { name: "Запустить проверки: Задание 5", exact: true })
    .click();
  await expect(
    candidate.locator(".code-feedback").getByText(/Пройдено 1 из 1/),
  ).toBeVisible({ timeout: 250000 });
  await candidate
    .getByRole("button", { name: "Завершить набор", exact: true })
    .click();
  const finish = candidate.getByRole("dialog", {
    name: "Проверьте ответы перед завершением",
  });
  await expect(finish).toContainText(/На сервере сохранено ответов: 5 из 5/);
  await expect(finish).toContainText("Все задания заполнены.");
  await finish
    .getByRole("button", { name: "Подтвердить завершение", exact: true })
    .click();
  await expect(
    candidate.getByRole("heading", {
      name: "Ожидается ручная проверка",
      exact: true,
    }),
  ).toBeVisible();
  await author
    .getByRole("button", { name: "Ручная проверка", exact: true })
    .click();
  await expect(
    candidate.getByText("Предварительный балл · проверка продолжается", {
      exact: true,
    }),
  ).toBeVisible();
  const review = author
    .locator(".record-row")
    .filter({ hasText: "Синтетический ответ с объяснением" });
  await review.getByLabel("Оценка, от 0 до 100", { exact: true }).fill("100");
  await review
    .getByLabel("Обратная связь", { exact: true })
    .fill("Ответ соответствует рубрике синтетического набора.");
  await review
    .getByRole("button", { name: "Сохранить проверку", exact: true })
    .click();
  await expect(
    author.getByText("Проверка сохранена. Результат доступен кандидату", {
      exact: true,
    }),
  ).toBeVisible();
  await candidate
    .getByRole("button", { name: "Обновить результат", exact: true })
    .click();
  await expect(
    candidate.getByRole("heading", { name: "Результат набора", exact: true }),
  ).toBeVisible();
  await expect(candidate.locator(".score")).toHaveText("100 / 100");
  await candidate.screenshot({
    path: testInfo.outputPath("bank-result.png"),
    fullPage: true,
  });
  await authorContext.close();
  await candidateContext.close();
});

test("после дедлайна отправляется серверный черновик, а локальное изменение не подменяет результат", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await login(page, "Кандидат А");
  const attemptId = "deadline-e2e-attempt";
  const startedAt = await page.evaluate(() => Date.now());
  const deadline = new Date(startedAt + 12000).toISOString();
  const task = {
    id: "deadline-e2e-task",
    type: "single_choice",
    title: "Синтетический вопрос с сохранённым ответом",
    prompt: "Выберите сохранённый сервером вариант.",
    skills: ["python"],
    weight: 1,
    expected_minutes: 1,
    options: [
      { id: "server-answer", text: "Серверный ответ" },
      { id: "local-answer", text: "Локальное изменение" },
    ],
    absolute_tolerance: 0,
    relative_tolerance: 0,
    unit: "",
    rubric: "Синтетическая проверка выбора.",
    answer_limit: 1000,
    language: "python",
    starter_code: "",
    examples: [],
    runtime_limits: { wall_seconds: 2, memory_mb: 64 },
  };
  const serverAttempt = {
    id: attemptId,
    version_id: "deadline-e2e-version",
    revision: 7,
    status: "in_progress",
    deadline,
    version: {
      id: "deadline-e2e-version",
      bank_id: "deadline-e2e-bank",
      number: 1,
      revision: 1,
      state: "published",
      scope: "platform",
      company_label: "Синтетический тест",
      title: "Сценарий дедлайна",
      specialization: "backend",
      grade: "junior",
      time_limit_minutes: 1,
      tasks: [task],
    },
    answers: { [task.id]: "server-answer" },
    result: null,
  };
  const submittedAttempt = {
    ...serverAttempt,
    revision: 8,
    status: "completed",
    submitted_at: new Date(startedAt + 13800).toISOString(),
    result: {
      score: 100,
      pending_count: 0,
      completed: true,
      tasks: [
        {
          task_id: task.id,
          type: "single_choice",
          score: 100,
          status: "scored",
          feedback: null,
        },
      ],
    },
  };
  let patchCalls = 0;
  let submitPayload: { revision: number } | null = null;
  await page.route(/\/api\/v1\/candidate\/bank-attempts\/deadline-e2e-attempt(?:\/submit)?$/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/submit") && request.method() === "POST") {
      submitPayload = request.postDataJSON() as { revision: number };
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(submittedAttempt) });
      return;
    }
    if (request.method() === "PATCH") {
      patchCalls++;
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ message: "Время попытки истекло; можно отправить сохранённые ответы" }) });
      return;
    }
    if (request.method() === "GET") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(serverAttempt) });
      return;
    }
    await route.continue();
  });

  await page.clock.install({ time: new Date(startedAt) });
  await page.goto(`/#/candidate/practice/${attemptId}`);
  await expect(page.getByRole("radio", { name: "Серверный ответ", exact: true })).toBeChecked();
  // Загрузка идёт с работающими таймерами; затем фиксируем точную границу.
  await page.clock.pauseAt(new Date(startedAt + 11800));
  await page.getByRole("radio", { name: "Локальное изменение", exact: true }).check();
  await expect(page.getByText("Сохранение ответа…", { exact: true })).toBeVisible();
  // Deadline is +12000ms; the pending 850ms autosave would fire at +12650ms.
  // Advance beyond both so the client must check the timestamp, not stale UI state.
  await page.clock.fastForward(2000);
  await expect(page.getByRole("alert")).toContainText("Время закончилось");
  expect(patchCalls).toBe(0);

  await page.getByRole("button", { name: "Отправить сохранённые ответы" }).click();
  const finish = page.getByRole("dialog", { name: "Проверьте ответы перед завершением" });
  await expect(finish).toContainText(/На сервере сохранено ответов: 1 из 1/);
  await expect(finish).toContainText(/Локально изменено заданий: 1/);
  await expect(finish).toContainText("После дедлайна в результат войдут только серверные ответы.");
  await finish.getByText("Скопировать локальные изменения перед отправкой").click();
  await expect(finish.locator("pre.review-answer")).toContainText("local-answer");
  await finish.getByRole("button", { name: "Подтвердить завершение", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Результат набора", exact: true })).toBeVisible();
  expect(patchCalls).toBe(0);
  expect(submitPayload).toEqual({ revision: 7 });
  const persistedAnswer = page.getByRole("radio", { name: "Серверный ответ", exact: true });
  const localAnswer = page.getByRole("radio", { name: "Локальное изменение", exact: true });
  await expect(persistedAnswer).toBeChecked();
  await expect(persistedAnswer).toBeDisabled();
  await expect(localAnswer).not.toBeChecked();
  await expect(page.locator("details.unsent-answers")).toContainText("local-answer");
});

test("импорт, версии и маршруты доступны с клавиатуры на 390 / 768 / 1440 px", async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "Демо-команда X");
  await page
    .getByRole("button", { name: "Конструктор заданий", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Импорт материалов", exact: true })
    .click();
  await page.getByLabel("Файл готовых заданий", { exact: true }).setInputFiles({
    name: "broken.json",
    mimeType: "application/json",
    buffer: Buffer.from('{"bad":"source"}'),
  });
  await page
    .getByRole("button", { name: "Проверить файл", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Исправьте ошибки в источнике",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить импорт", exact: true }),
  ).toBeDisabled();
  const title = "Импорт E2E " + Date.now();
  const importedDocument = {
    schema_version: "fsp-bank-v1",
    external_id: "e2e-" + Date.now(),
    scope: "employer",
    title,
    specialization: "backend",
    grade: "junior",
    time_limit_minutes: 60,
    tasks: [
      {
        id: "sum",
        type: "numeric",
        title: "Сумма",
        prompt: "Сколько будет 2 + 2?",
        skills: ["python"],
        numeric_answer: 4,
      },
    ],
  };
  await page.getByLabel("Файл готовых заданий", { exact: true }).setInputFiles({
    name: "bank.json",
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
  await page
    .getByRole("button", { name: "Подтвердить импорт", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  const address = page.url();
  await page.getByRole("button", { name: "Компания", exact: true }).click();
  await page.goBack();
  await expect(page).toHaveURL(address);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: testInfo.outputPath("constructor-" + width + ".png"),
      fullPage: true,
    });
  }
  await page
    .getByRole("button", { name: "Предпросмотр кандидата", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", {
      name: "Так выглядит версия для кандидата",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Опубликовать набор", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Копировать в новую версию", exact: true })
    .click();
  await expect(
    page.getByText("Создана новая черновая версия", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Открыть версию", { exact: true })).toHaveValue(
    /.+/,
  );
  const zipDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт ZIP", exact: true }).click();
  expect((await zipDownload).suggestedFilename()).toBe("fsp-bank.zip");
  await page.getByRole("button", { name: "Все наборы", exact: true }).click();
  await page
    .getByRole("button", { name: "Импорт материалов", exact: true })
    .click();
  await page.getByLabel("Файл готовых заданий", { exact: true }).setInputFiles({
    name: "mapped.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "Код,Тип,Название,Условие,Навыки,Эталон\nvalue,numeric,Сумма,Сколько будет 2 плюс 2?,python,4\n",
    ),
  });
  const mapping = {
    Код: "id",
    Тип: "type",
    Название: "title",
    Условие: "prompt",
    Навыки: "skills",
    Эталон: "numeric_answer",
  };
  for (const [incoming, canonical] of Object.entries(mapping))
    await page
      .getByLabel("Сопоставление: " + incoming, { exact: true })
      .selectOption(canonical);
  await page
    .getByRole("button", { name: "Проверить файл", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Можно сохранить черновик",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Подтвердить импорт", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Импорт CSV", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("оценка грейда сохраняет ответы при переходе, Back и reload; приватность доступна с клавиатуры", async ({
  page,
}) => {
  const assessmentExitPrompts: string[] = [];
  page.on("dialog", async (dialog) => {
    if (dialog.type() === "confirm") assessmentExitPrompts.push(dialog.message());
    await dialog.accept();
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const email = "draft-" + Date.now() + "@example.invalid";
  await page.getByLabel("Демонстрационная почта", { exact: true }).fill(email);
  const password = crypto.randomUUID();
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("checkbox", { name: /Согласен/ }).check();
  await page
    .getByRole("button", { name: "Создать тестовый аккаунт", exact: true })
    .click();
  await page
    .locator(".mail-row")
    .filter({ hasText: email })
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  await page
    .getByRole("button", { name: "Начать оценку", exact: true })
    .click();
  const assessmentPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await expect(assessmentPages.getByRole("status")).toContainText("страница 1 из 12");
  const firstAnswer = page
    .locator(".assessment-question fieldset")
    .getByRole("radio")
    .first();
  await firstAnswer.check();
  await expect(
    page.getByText("Ответы сохранены на сервере", { exact: true }),
  ).toBeVisible();
  const address = page.url();
  // Медленное сохранение и немедленный переход проверяют flush последней правки.
  await page.route("**/assessments/attempts/*/draft", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.continue();
  });
  await assessmentPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(assessmentPages.getByRole("status")).toContainText("страница 2 из 12");
  const secondAnswer = page
    .locator(".assessment-question fieldset")
    .getByRole("radio")
    .first();
  await secondAnswer.check();
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await expect(
    page.getByLabel("Ожидаемая зарплата от, руб./мес.", { exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(address);
  await expect(firstAnswer).toBeChecked();
  await assessmentPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(secondAnswer).toBeChecked();
  await page.reload();
  await expect(firstAnswer).toBeChecked();
  const reloadedAssessmentPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await reloadedAssessmentPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(secondAnswer).toBeChecked();
  await expect(
    page.getByText("Продолжение сохранённой попытки", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Приватность", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Получатели контакта", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Связь ФСП · mock", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Войти через ФСП ID (демо)", exact: true }).focus();
  await expect(
    page.getByRole("button", { name: "Войти через ФСП ID (демо)", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  const thirdQuestionPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await thirdQuestionPages.getByRole("button", { name: /Следующая страница/ }).click();
  await thirdQuestionPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(thirdQuestionPages.getByRole("status")).toContainText("страница 3 из 12");
  const thirdAnswer = page
    .locator(".assessment-question fieldset")
    .getByRole("radio")
    .first();
  await thirdAnswer.check();
  await expect(
    page.getByText("Ответы сохранены на сервере", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /Сначала доказательства/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Вход с паролем", exact: true })
    .click();
  await page.getByLabel("Демонстрационная почта", { exact: true }).fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Войти с паролем", exact: true })
    .click();
  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  const restoredQuestionPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await restoredQuestionPages.getByRole("button", { name: /Следующая страница/ }).click();
  await restoredQuestionPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(thirdAnswer).toBeChecked();
  expect(assessmentExitPrompts).toHaveLength(3);
  expect(assessmentExitPrompts.every((message) => message.includes("Покинуть оценку"))).toBe(true);
});
