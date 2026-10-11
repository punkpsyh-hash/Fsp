import { questionTitle } from "./question";
import { test, expect, type Locator, type Page } from "@playwright/test";
import { scenarioAnswer } from "../scripts/scenario-oracle.mjs";

async function login(page: Page, name: string) {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(
    page.getByRole("navigation", { name: "Разделы кабинета" }),
  ).toBeVisible();
}

// Решаем только видимый текст вопроса. E2E не читает answer API и не смотрит
// ключи/seed на сервере; новая форма может менять порядок и параметры.
async function juniorBackendAnswer(page: Page, title: string): Promise<string> {
  const attempt = await (await page.request.get('/api/v1/candidate/active-assessment')).json();
  if (['scenarios-v5', 'scenarios-v6'].includes(attempt?.version)) {
    const normalize = (value: string) => value.replace(/\s+/g, ' ').trim();
    const question = attempt.questions.find((row: { title: string }) => normalize(row.title) === normalize(title));
    if (!question) throw new Error('Видимый сценарий отсутствует в публичной форме');
    return scenarioAnswer(question, attempt.grade);
  }
  const range = title.match(/range\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (range) {
    const [, start, stop, step] = range.map(Number);
    return String(Math.ceil(Math.max(0, stop - start) / step));
  }
  const state = title.match(/Список xs = \[([^\]]+)\]/);
  if (state) {
    const values = state[1].split(",").map(Number);
    const appended = title.match(/xs\.append\((\d+)\)/);
    if (appended) return String(values.reduce((sum, value) => sum + value, 0) + Number(appended[1]));
  }
  const count = title.match(/В таблице (\d+) строк, у (\d+) строк/);
  if (count) return String(Number(count[1]) - Number(count[2]));
  const join = title.match(/У (\d+) есть по (\d+) заказа/);
  if (join) {
    const matches = Number(join[1]) * Number(join[2]);
    return String(title.includes("LEFT JOIN") ? matches + Number(title.match(/В users (\d+)/)?.[1] || 0) - Number(join[1]) : matches);
  }
  const retry = title.match(/создаёт (\d+) разных операций POST/);
  if (retry) return String(Number(retry[1]) + Number(title.match(/ещё (\d+) операций/)?.[1] || 0));
  const access = title.match(/(\d+) компаний просматривают кандидата\. Кандидат разрешил контакт ровно (\d+) компаниям/);
  if (access) return String(Number(access[1]) - Number(access[2]));
  throw new Error(`Неизвестный синтетический вопрос: ${title}`);
}

async function answerAssessmentAndWaitForSave(page: Page, answer: string) {
  const saved = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/assessments/attempts/") &&
      response.url().endsWith("/draft") &&
      response.request().method() === "PUT",
  );
  await page.getByRole("radio", { name: answer, exact: true }).check();
  expect((await saved).ok()).toBeTruthy();
  await expect(
    page.getByText("Ответы сохранены на сервере", { exact: true }),
  ).toBeVisible();
}

async function revealPagedRow(page: Page, label: string, row: Locator) {
  const pages = page.getByRole("navigation", { name: `Страницы: ${label}` });
  const status = pages.getByRole("status");
  await expect
    .poll(async () =>
      Number((await status.innerText()).match(/из (\d+)/)?.[1] || 0),
    )
    .toBeGreaterThan(0);
  const firstPage = pages.getByRole("button", {
    name: `Страница 1: ${label}`,
    exact: true,
  });
  if (await firstPage.isEnabled()) {
    await firstPage.click();
    await expect(status).toContainText(/страница 1 из/);
  }
  for (let attempt = 0; attempt < 32; attempt++) {
    if ((await row.count()) === 1) return;
    const next = pages.getByRole("button", { name: /Следующая страница/ });
    if (!(await next.isEnabled())) break;
    const currentPage = Number(
      (await status.innerText()).match(/страница (\d+) из/)?.[1],
    );
    await next.click();
    await expect(status).toContainText(
      new RegExp(`страница ${currentPage + 1} из`),
    );
  }
  await expect(row).toHaveCount(1);
}

test("предложение, принятие, изоляция компаний и отзыв контакта", async ({
  browser,
}) => {
  test.setTimeout(90_000);
  const x = await browser.newContext(),
    a = await browser.newContext(),
    y = await browser.newContext();
  const employer = await x.newPage(),
    candidate = await a.newPage(),
    other = await y.newPage();
  const clean = await browser.newContext();
  const auth = await (
    await clean.request.post("/api/v1/auth/demo-login", {
      data: { user_id: "demo-candidate-a" },
    })
  ).json();
  await clean.request.delete("/api/v1/candidate/contacts/demo-employer-x", {
    headers: { "X-CSRF-Token": auth.csrf },
  });
  await clean.close();
  await login(employer, "Демо-команда X");
  // Подбор приходит после оболочки кабинета: до строк нельзя листать страницы.
  await expect(employer.locator(".candidate-row").first()).toBeVisible();
  const first = employer.locator(".candidate-row").filter({ hasText: "P-104" });
  await revealPagedRow(employer, "Результаты подбора", first);
  await first.getByRole("button", { name: "Пригласить", exact: true }).click();
  const marker = "Синтетическое предложение браузерного теста " + Date.now();
  const dialog = employer.getByRole("dialog");
  await dialog.getByLabel("Условия и задачи").fill(marker);
  await dialog.getByRole("button", { name: "Отправить предложение" }).click();
  await expect(dialog).not.toBeVisible();
  await employer
    .getByRole("button", { name: "Отправленные", exact: true })
    .click();
  const sent = employer.locator(".offer-row").filter({ hasText: marker });
  await expect(sent.getByText("Контакт кандидата скрыт")).toBeVisible();
  await login(candidate, "Кандидат А");
  await candidate
    .getByRole("button", { name: "Входящие", exact: true })
    .click();
  const incoming = candidate.locator(".offer-row").filter({ hasText: marker });
  await incoming.getByRole("button", { name: "Отметить просмотр" }).click();
  await expect(
    incoming.getByText("Просмотрено", { exact: true }),
  ).toBeVisible();
  await incoming
    .getByRole("button", { name: "Принять и открыть контакт" })
    .click();
  await expect(incoming.getByText("Принято", { exact: true })).toBeVisible();
  await employer.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(sent.getByText(/Разрешённый контакт:/)).toBeVisible();
  await login(other, "Демо-команда Y");
  const outside = await other.request.get(
    "/api/v1/company/candidates/demo-candidate-a",
  );
  expect(await outside.json()).not.toHaveProperty("contact");
  await candidate
    .getByRole("button", { name: "Приватность", exact: true })
    .click();
  const grant = candidate
    .locator(".mail-row")
    .filter({ hasText: "Демо-команда X" });
  await grant.getByRole("button", { name: "Отозвать контакт" }).click();
  await expect(candidate.getByText("Доступ к контакту отозван")).toBeVisible();
  await employer.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(sent.getByText("Контакт отозван кандидатом")).toBeVisible();
  await x.close();
  await a.close();
  await y.close();
});

test("оценка: ответы переживают next/back/reload, сводка блокирует пропуски перед отправкой", async ({
  page,
}) => {
  page.on("dialog", async (dialog) => {
    if (dialog.type() === "beforeunload") await dialog.accept();
    else await dialog.dismiss();
  });
  test.setTimeout(90_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const email = "browser-" + Date.now() + "@example.invalid";
  await page.getByLabel("Демонстрационная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(crypto.randomUUID());
  await page.getByRole("checkbox", { name: /Согласен/ }).check();
  await page.getByRole("button", { name: "Создать тестовый аккаунт" }).click();
  const mail = page.locator(".mail-row").filter({ hasText: email });
  await mail.getByRole("button", { name: "Подтвердить вход" }).click();
  await page.getByLabel("Ожидаемая зарплата от, руб./мес.").fill("135000");
  await page.getByRole("button", { name: "Сохранить профиль" }).click();
  await expect(page.getByText(/Профиль сохранён/)).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Ожидаемая зарплата от, руб./мес.")).toHaveValue(
    "135000",
  );
  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  await page.getByRole("button", { name: "Начать оценку" }).click();
  const questionPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await expect(questionPages.getByRole("status")).toContainText("страница 1 из 12");
  await expect(page.locator("fieldset")).toHaveCount(1);

  // Неполную форму нельзя случайно отправить: сводка должна показать пропуски.
  const openAssessmentSummary = page.getByRole("button", { name: "Отправить ответы" });
  await openAssessmentSummary.click();
  const confirmation = page.getByRole("dialog", {
    name: "Проверка перед отправкой",
  });
  await expect(confirmation).toContainText("Отвечено 0 из 12. Без ответа: 12");
  const firstSkipped = confirmation.getByRole("button", { name: "Перейти к пропуску" });
  const returnToAnswers = confirmation.getByRole("button", { name: "Вернуться к ответам" });
  await expect(firstSkipped).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(returnToAnswers).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(firstSkipped).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirmation).not.toBeVisible();
  await expect(openAssessmentSummary).toBeFocused();
  await openAssessmentSummary.click();
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Перейти к пропуску" }).click();
  await expect(questionPages.getByRole("status")).toContainText("страница 1 из 12");

  const firstTitle = await questionTitle(page);
  const firstAnswer = await juniorBackendAnswer(page, firstTitle);
  await answerAssessmentAndWaitForSave(page, firstAnswer);
  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  const nextQuestion = questionPages.getByRole("button", { name: /Следующая страница/ });
  await nextQuestion.focus();
  await page.keyboard.press("Enter");
  await expect(questionPages.getByRole("status")).toContainText("страница 2 из 12");
  await questionPages.getByRole("button", { name: /Предыдущая страница/ }).click();
  await expect(page.getByRole("radio", { name: firstAnswer, exact: true })).toBeChecked();
  await page.reload();
  const restoredPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await expect(restoredPages.getByRole("status")).toContainText("страница 1 из 12");
  await expect(page.getByRole("radio", { name: firstAnswer, exact: true })).toBeChecked();

  for (let questionNumber = 1; questionNumber <= 12; questionNumber++) {
    const title = await questionTitle(page);
    if (questionNumber !== 1) {
      await answerAssessmentAndWaitForSave(page, await juniorBackendAnswer(page, title));
    }
    if (questionNumber < 12)
      await restoredPages.getByRole("button", { name: /Следующая страница/ }).click();
  }
  await page.evaluate(() => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    Object.defineProperty(document.documentElement, "requestFullscreen", {
      configurable: true,
      value: () => {
        Object.defineProperty(document, "fullscreenElement", {
          configurable: true, value: document.documentElement,
        });
        document.dispatchEvent(new Event("fullscreenchange"));
        return Promise.resolve();
      },
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: () => {
        document.documentElement.dataset.examExitCount = String(
          Number(document.documentElement.dataset.examExitCount || 0) + 1,
        );
        Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
        document.dispatchEvent(new Event("fullscreenchange"));
        return Promise.resolve();
      },
    });
  });
  await page.getByRole("button", { name: "На весь экран" }).click();
  await expect(page.getByText(/Для выхода нажмите Esc/)).toBeVisible();
  await page.getByRole("button", { name: "Отправить ответы" }).click();
  const completeSummary = page.getByRole("dialog", {
    name: "Проверка перед отправкой",
  });
  await expect(completeSummary).toContainText("Отвечено 12 из 12. Без ответа: 0");
  await completeSummary.getByRole("button", { name: "Подтвердить отправку" }).click();
  await expect(page.getByText("Оценочная форма пройдена")).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.examExitCount)).toBe("1");
  const report = page.getByRole("region", { name: "Разбор оценки", exact: true });
  await expect(report.getByText("12 из 12 верно", { exact: true })).toBeVisible();
  await expect(report.locator(".skill-report-row")).toHaveCount(3);
  await expect(report.getByRole("progressbar")).toHaveCount(3);
  await report.locator(".answer-explanation summary").first().click();
  await expect(report.locator(".answer-explanation").first()).toContainText("Эталон сохранённой формы");
  const reportPages = report.getByRole("navigation", { name: "Страницы: Разбор заданий" });
  await expect(reportPages.getByRole("status")).toContainText("1–4 из 12");
  await reportPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(reportPages.getByRole("status")).toContainText("5–8 из 12");
  await page.getByRole("button", { name: "История", exact: true }).click();
  const reviewRequest = page.waitForResponse((response) =>
    /\/api\/v1\/assessments\/attempts\/[^/]+$/.test(new URL(response.url()).pathname) &&
    response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "Просмотреть вопросы и ответы" }).first().click();
  const reviewResponse = await reviewRequest;
  expect(reviewResponse.ok()).toBeTruthy();
  await expect(page).toHaveURL(/#\/candidate\/assessment\/[^/]+$/);
  const reviewPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await expect(reviewPages.getByRole("status")).toContainText("страница 1 из 12");
  const reviewedFirstAnswer = page.getByRole("radio", { name: firstAnswer, exact: true });
  await expect(reviewedFirstAnswer).toBeChecked();
  await expect(reviewedFirstAnswer).toBeDisabled();
  await reviewPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(reviewPages.getByRole("status")).toContainText("страница 2 из 12");
  await page.reload();
  const reloadedReviewPages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await expect(reloadedReviewPages.getByRole("status")).toContainText("страница 1 из 12");
  await expect(page.getByRole("region", { name: "Разбор оценки", exact: true }).getByText("12 из 12 верно", { exact: true })).toBeVisible();
  await expect(page.getByRole("radio", { name: firstAnswer, exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: firstAnswer, exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Приватность", exact: true }).click();
  await page.getByRole("button", { name: "Опубликовать профиль" }).click();
  await expect(
    page.getByRole("heading", { name: "Профиль опубликован" }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Приватность", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Профиль опубликован" }),
  ).toBeVisible();
});

test("оценка сохраняет самое новое поколение ответа после ожидания медленного autosave", async ({ page }) => {
  page.on("dialog", async (dialog) => {
    if (dialog.type() === "beforeunload") await dialog.accept();
    else await dialog.dismiss();
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const frozenAt = Date.now();
  await page.clock.install({ time: new Date(frozenAt - 60_000) });
  await page.goto("/");
  const email = `autosave-${Date.now()}@example.invalid`;
  await page.getByLabel("Демонстрационная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(crypto.randomUUID());
  await page.getByRole("checkbox", { name: /Согласен/ }).check();
  await page.getByRole("button", { name: "Создать тестовый аккаунт" }).click();
  await page
    .locator(".mail-row")
    .filter({ hasText: email })
    .getByRole("button", { name: "Подтвердить вход" })
    .click();
  await page.getByLabel("Ожидаемая зарплата от, руб./мес.").fill("120000");
  await page.getByRole("button", { name: "Сохранить профиль" }).click();
  await expect(page.getByText(/Профиль сохранён/)).toBeVisible();

  // Минутный запас больше лимита теста: pauseAt не получает время из прошлого.
  await page.clock.pauseAt(new Date(frozenAt));
  let releaseFirst!: () => void;
  let announceFirst!: () => void;
  const barrier = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const firstStarted = new Promise<void>((resolve) => { announceFirst = resolve; });
  const draftBodies: { answers: Record<string, string>; expected_revision: number }[] = [];
  await page.route("**/api/v1/assessments/attempts/*/draft", async (route) => {
    const body = route.request().postDataJSON() as {
      answers: Record<string, string>;
      expected_revision: number;
    };
    draftBodies.push(body);
    if (draftBodies.length === 1) {
      announceFirst();
      await barrier;
    }
    await route.continue();
  });

  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  await page.getByRole("button", { name: "Начать оценку" }).click();
  const pages = page.getByRole("navigation", { name: "Страницы: Вопросы оценки" });
  await expect(pages.getByRole("status")).toContainText("страница 1 из 12");
  const options = page.locator(".assessment-question fieldset label");
  await expect(options).toHaveCount(4);
  const labels = (await options.allTextContents()).map((label) => label.trim());
  const [answerA, answerB, answerC] = labels;
  expect(answerC).toBeTruthy();

  await page.getByRole("radio", { name: answerA, exact: true }).check();
  await page.clock.fastForward(750);
  await firstStarted;
  expect(draftBodies).toHaveLength(1);
  expect(Object.values(draftBodies[0].answers)).toEqual([answerA]);

  await page.getByRole("radio", { name: answerB, exact: true }).check();
  await page.clock.fastForward(750);
  // The B autosave timer is now waiting on the still-pending A request.
  expect(draftBodies).toHaveLength(1);
  await page.getByRole("radio", { name: answerC, exact: true }).check();
  const savedC = page.waitForResponse((response) => {
    if (!response.url().includes("/api/v1/assessments/attempts/") ||
        !response.url().endsWith("/draft") ||
        response.request().method() !== "PUT") return false;
    const body = response.request().postDataJSON() as { answers: Record<string, string> };
    return Object.values(body.answers).includes(answerC);
  });
  releaseFirst();
  expect((await savedC).ok()).toBeTruthy();
  await expect(page.getByText("Ответы сохранены на сервере", { exact: true })).toBeVisible();
  expect(draftBodies).toHaveLength(2);
  expect(Object.values(draftBodies[1].answers)).toEqual([answerC]);

  await page.reload();
  await expect(page.getByRole("navigation", { name: "Страницы: Вопросы оценки" })).toBeVisible();
  await expect(page.getByRole("radio", { name: answerC, exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: answerA, exact: true })).not.toBeChecked();
});

test("practice navigation flush не зацикливается, если дедлайн проходит во время активного autosave", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await login(page, "Кандидат А");
  const attemptId = "navigation-deadline-race";
  const startedAt = await page.evaluate(() => Date.now());
  const deadline = new Date(startedAt + 20000).toISOString();
  const task = {
    id: "navigation-race-task",
    type: "single_choice",
    title: "Синтетический autosave race",
    prompt: "Три ответа для проверки порядка сохранения.",
    skills: ["python"],
    weight: 1,
    expected_minutes: 1,
    options: [
      { id: "server-answer", text: "Сохранённый ответ" },
      { id: "local-a", text: "Локальный ответ A" },
      { id: "local-b", text: "Локальный ответ B" },
    ],
    absolute_tolerance: 0,
    relative_tolerance: 0,
    unit: "",
    rubric: "Синтетическая проверка сохранения.",
    answer_limit: 1000,
    language: "python",
    starter_code: "",
    examples: [],
    runtime_limits: { wall_seconds: 2, memory_mb: 64 },
  };
  const savedAttempt = {
    id: attemptId,
    version_id: "navigation-race-version",
    revision: 7,
    status: "in_progress",
    deadline,
    version: {
      id: "navigation-race-version",
      bank_id: "navigation-race-bank",
      number: 1,
      revision: 1,
      state: "published",
      scope: "platform",
      company_label: "Синтетический тест",
      title: "Проверка перехода после срока",
      specialization: "backend",
      grade: "junior",
      time_limit_minutes: 1,
      tasks: [task],
    },
    answers: { [task.id]: "server-answer" },
    result: null,
  };
  let releasePatch!: () => void;
  let announcePatch!: () => void;
  const patchBarrier = new Promise<void>((resolve) => { releasePatch = resolve; });
  const patchStarted = new Promise<void>((resolve) => { announcePatch = resolve; });
  let patchCount = 0;
  let patchBody: { revision: number; answers: Record<string, unknown> } | null = null;
  const confirmMessages: string[] = [];
  let acceptNavigation = false;

  await page.route(/\/api\/v1\/candidate\/bank-attempts\/navigation-deadline-race$/, async (route) => {
    const request = route.request();
    if (request.method() === "PATCH") {
      patchCount++;
      patchBody = request.postDataJSON() as { revision: number; answers: Record<string, unknown> };
      announcePatch();
      await patchBarrier;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...savedAttempt,
          revision: 8,
          answers: { [task.id]: "local-a" },
        }),
      });
      return;
    }
    if (request.method() === "GET") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(savedAttempt) });
      return;
    }
    await route.continue();
  });
  page.on("dialog", async (dialog) => {
    if (dialog.type() !== "confirm") {
      await dialog.dismiss();
      return;
    }
    confirmMessages.push(dialog.message());
    if (acceptNavigation) await dialog.accept();
    else await dialog.dismiss();
  });

  await page.clock.install({ time: new Date(startedAt) });
  await page.goto(`/#/candidate/practice/${attemptId}`);
  await expect(page.getByRole("radio", { name: "Сохранённый ответ", exact: true })).toBeChecked();
  await page.clock.pauseAt(new Date(startedAt + 18000));
  await page.getByRole("radio", { name: "Локальный ответ A", exact: true }).check();
  await page.clock.fastForward(850);
  await patchStarted;
  await page.getByRole("radio", { name: "Локальный ответ B", exact: true }).check();

  const leaveAttempt = page.getByRole("button", { name: "Профиль", exact: true }).click();
  // Keep PATCH A pending while the deadline passes and the debounced save for B is waiting.
  await page.clock.fastForward(1200);
  expect(confirmMessages).toHaveLength(0);
  releasePatch();
  await leaveAttempt;
  expect(patchCount).toBe(1);
  expect(patchBody).toEqual({
    revision: 7,
    answers: { [task.id]: "local-a" },
  });
  await expect.poll(() => confirmMessages.length).toBe(1);
  expect(confirmMessages[0]).toMatch(/Время практики закончилось.*Перейти дальше\?/);
  await expect(page).toHaveURL(new RegExp(`/candidate/practice/${attemptId}$`));
  await expect(page.getByRole("radio", { name: "Локальный ответ B", exact: true })).toBeChecked();

  acceptNavigation = true;
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await expect(page.getByLabel("Ожидаемая зарплата от, руб./мес.")).toBeVisible();
  await expect.poll(() => confirmMessages.length).toBe(2);
  expect(patchCount).toBe(1);
});

test("мобильная компоновка и отсутствие ошибок браузера", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Сначала доказательства/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("mobile.png"), fullPage: true });
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await expect(page.locator(".candidate-row").first()).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: testInfo.outputPath("mobile-bank.png"),
    fullPage: true,
  });
});

test("вакансия, добровольный отклик, доступ выбранной компании и отзыв", async ({
  browser,
}) => {
  test.setTimeout(90_000);
  const clean = await browser.newContext();
  const auth = await (
    await clean.request.post("/api/v1/auth/demo-login", {
      data: { user_id: "demo-candidate-a" },
    })
  ).json();
  const revoked = await clean.request.delete(
    "/api/v1/candidate/contacts/demo-employer-x",
    { headers: { "X-CSRF-Token": auth.csrf } },
  );
  expect(revoked.status()).toBe(204);
  await clean.close();
  const x = await browser.newContext(),
    a = await browser.newContext(),
    y = await browser.newContext();
  const employer = await x.newPage(),
    candidate = await a.newPage(),
    other = await y.newPage();
  await login(employer, "Демо-команда X");
  await employer.getByRole("button", { name: "Вакансии", exact: true }).click();
  const title = "Синтетическая вакансия E2E " + Date.now();
  await employer.getByLabel("Название вакансии", { exact: true }).fill(title);
  await employer.getByLabel("Состояние вакансии").selectOption("published");
  await employer.getByRole("button", { name: "Создать вакансию" }).click();
  await expect(
    employer.getByText("Вакансия сохранена", { exact: true }),
  ).toBeVisible();
  await login(candidate, "Кандидат А");
  await candidate
    .getByRole("button", { name: "Вакансии", exact: true })
    .click();
  const vacancy = candidate.locator(".record-row").filter({ hasText: title });
  await vacancy
    .getByRole("button", { name: "Откликнуться и разрешить контакт" })
    .click();
  await expect(
    candidate.getByText(
      "Отклик отправлен. Контакт разрешён только этой компании",
      { exact: true },
    ),
  ).toBeVisible();
  await candidate
    .getByRole("button", { name: "Мои отклики", exact: true })
    .click();
  const application = candidate
    .locator(".record-row")
    .filter({ hasText: title });
  await expect(application.getByText(/Отправлен/)).toBeVisible();
  await employer.getByRole("button", { name: "Отклики", exact: true }).click();
  const incoming = employer.locator(".record-row").filter({ hasText: title });
  await expect(incoming.getByText(/Разрешённый контакт:/)).toBeVisible();
  await login(other, "Демо-команда Y");
  expect(
    await (
      await other.request.get("/api/v1/company/candidates/demo-candidate-a")
    ).json(),
  ).not.toHaveProperty("contact");
  await application.getByRole("button", { name: "Отозвать отклик" }).click();
  await expect(
    candidate.getByText("Отклик отозван", { exact: true }),
  ).toBeVisible();
  await employer.getByRole("button", { name: "Обновить отклики" }).click();
  await expect(
    incoming.getByText("Контакт недоступен или отозван"),
  ).toBeVisible();
  await x.close();
  await a.close();
  await y.close();
});

test("потребность Frontend открывает нужную категорию и сохраняет shortlist", async ({
  page,
}) => {
  await login(page, "Демо-команда X");
  await page.getByRole("button", { name: "Потребности", exact: true }).click();
  const need = page
    .locator(".record-row")
    .filter({ hasText: "Frontend-разработчик JavaScript" });
  await revealPagedRow(page, "Потребности команды", need);
  await need.getByRole("button", { name: "Подобрать кандидатов" }).click();
  await expect(page.getByLabel("Специализация", { exact: true })).toHaveValue(
    "frontend",
  );
  const first = page.locator(".candidate-row").first();
  await expect(first.getByText(/Frontend/)).toBeVisible();
  const alias = await first.locator("h3").innerText();
  await first.getByRole("button", { name: "В мой список" }).click();
  await expect(
    page.getByText("Кандидат сохранён в списке", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Мой список", exact: true }).click();
  await expect(
    page.locator(".candidate-row").filter({ hasText: alias }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Мой список", exact: true }).click();
  await expect(
    page.locator(".candidate-row").filter({ hasText: alias }),
  ).toBeVisible();
});
