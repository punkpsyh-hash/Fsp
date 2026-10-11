import { expect, test } from "@playwright/test";

test("отправка результата ждёт последние сигналы даже при задержке сети", async ({ page }) => {
  await page.goto("/");
  const email = `integrity-final-${Date.now()}@example.invalid`;
  await page.getByLabel("Демонстрационная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(crypto.randomUUID());
  await page.getByRole("checkbox", { name: /Согласен/ }).check();
  await page.getByRole("button", { name: "Создать тестовый аккаунт" }).click();
  await page.locator(".mail-row").filter({ hasText: email })
    .getByRole("button", { name: "Подтвердить вход" }).click();
  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  const started = page.waitForResponse(response =>
    response.url().endsWith("/assessments/attempts") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Начать оценку" }).click();
  const attempt = await (await started).json();
  await expect(page.locator(".assessment-question")).toBeVisible();
  const questionPages = page.getByRole("navigation", { name: "Страницы: Вопросы оценки" });
  for (let index = 0; index < attempt.questions.length; index++) {
    await expect(questionPages.getByRole("status")).toContainText(`страница ${index + 1} из`);
    await page.locator(".assessment-question input[type=radio]").first().check();
    if (index < attempt.questions.length - 1) {
      await questionPages.getByRole("button", { name: /Следующая страница/ }).click();
    }
  }
  await expect(page.getByRole("status").filter({ hasText: "Отвечено" })).toContainText("Отвечено 12 из 12");
  let deliveredCopies = false;
  await page.route("**/integrity", async route => {
    const hasCopies = route.request().postDataJSON().events.some((e: { type: string }) => e.type === "copy");
    if (hasCopies) await new Promise(resolve => setTimeout(resolve, 375));
    const response = await route.fetch();
    if (hasCopies) deliveredCopies = response.status() === 202;
    await route.fulfill({ response });
  });
  await page.route("**/submit", async route => {
    expect(deliveredCopies).toBe(true);
    await route.continue();
  });
  await page.locator(".assessment-question").evaluate(element => {
    for (let i = 0; i < 4; i++) element.dispatchEvent(new ClipboardEvent("copy", { bubbles: true, cancelable: true }));
  });
  await page.getByRole("button", { name: "Отправить ответы" }).click();
  const submitted = page.waitForResponse(response => response.url().endsWith("/submit"));
  await page.getByRole("dialog", { name: "Проверка перед отправкой" })
    .getByRole("button", { name: "Подтвердить отправку" }).click();
  const response = await submitted;
  expect(response.ok()).toBe(true);
  expect((await response.json()).integrity.signals).toEqual(expect.arrayContaining([
    expect.objectContaining({ code: "clipboard_copies", level: "flagged", value: 4 }),
  ]));
});

test.beforeAll(async ({}, testInfo) => {
  if (testInfo.project.name !== "chromium") {
    testInfo.setTimeout(70_000);
    await new Promise((resolve) => setTimeout(resolve, 61_000));
  }
});

test("оценка скрывает вопрос при уходе и требует явного продолжения без потери ответа", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await page.goto("/");
  const email = `exam-${Date.now()}@example.invalid`;
  await page.getByLabel("Демонстрационная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(crypto.randomUUID());
  await page.getByRole("checkbox", { name: /Согласен/ }).check();
  await page.getByRole("button", { name: "Создать тестовый аккаунт" }).click();
  await page.locator(".mail-row").filter({ hasText: email })
    .getByRole("button", { name: "Подтвердить вход" }).click();
  await page.getByLabel("Ожидаемая зарплата от, руб./мес.").fill("135000");
  await page.getByRole("button", { name: "Сохранить профиль" }).click();
  await page.getByRole("button", { name: "Оценка", exact: true }).click();

  // На старте некоторые headless-окна сообщают hasFocus=false: это не пауза.
  await page.evaluate(() => Object.defineProperty(document, "hasFocus", {
    configurable: true, value: () => false,
  }));
  await page.getByRole("button", { name: "Начать оценку" }).click();
  const question = page.locator(".assessment-question");
  const resume = page.getByRole("button", { name: "Продолжить оценку" });
  await expect(question).toBeVisible();
  const timer = page.locator(".assessment-toolbar .evidence");
  const before = await timer.innerText();

  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(question).toHaveCount(0);
  await expect(resume).toBeDisabled();
  await expect(page.getByRole("button", { name: "Отправить ответы" })).toBeDisabled();
  await expect.poll(async () => (await timer.innerText()) !== before).toBe(true);
  await page.evaluate(() => {
    Reflect.deleteProperty(document, "visibilityState");
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(resume).toBeEnabled();
  await expect(question).toHaveCount(0);
  await resume.click();
  await expect(question).toBeVisible();

  const saved = page.waitForResponse((response) =>
    response.url().endsWith("/draft") && response.request().method() === "PUT");
  const answer = page.locator(".assessment-question input[type=radio]").first();
  await answer.check();
  expect((await saved).ok()).toBe(true);

  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(question).toHaveCount(0);
  await expect(resume).toBeDisabled();
  if (testInfo.project.name === "chromium") {
    await page.screenshot({ path: testInfo.outputPath("exam-paused.png"), fullPage: true });
  }
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(resume).toBeEnabled();
  await resume.click();
  await expect(answer).toBeChecked();

  // Системный fullscreenchange без нашего запроса не меняет состояние.
  await page.evaluate(() => document.dispatchEvent(new Event("fullscreenchange")));
  await expect(question).toBeVisible();
  await page.evaluate(() => Object.defineProperty(document, "fullscreenEnabled", {
    configurable: true, value: false,
  }));
  await page.getByRole("button", { name: "На весь экран" }).click();
  await expect(page.getByText(/Полноэкранный режим недоступен/)).toBeVisible();
  await expect(question).toBeVisible();

  await page.evaluate(() => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    Object.defineProperty(document.documentElement, "requestFullscreen", {
      configurable: true, value: () => Promise.reject(new Error("denied")),
    });
  });
  await page.getByRole("button", { name: "На весь экран" }).click();
  await expect(page.getByText(/Браузер не разрешил полноэкранный режим/)).toBeVisible();
  await expect(question).toBeVisible();

  await page.evaluate(() => {
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
  });
  await page.getByRole("button", { name: "На весь экран" }).click();
  await expect(page.getByText(/Для выхода нажмите Esc/)).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
    document.dispatchEvent(new Event("fullscreenchange"));
  });
  await expect(question).toHaveCount(0);
  await resume.click();
  await expect(answer).toBeChecked();

  await page.getByRole("button", { name: "Отправить ответы" }).click();
  const summary = page.getByRole("dialog", { name: "Проверка перед отправкой" });
  await expect(summary).toBeVisible();
  await summary.getByRole("button", { name: "Вернуться к ответам" }).click();
  await expect(question).toBeVisible();

  await page.evaluate(() => Object.defineProperty(document, "exitFullscreen", {
    configurable: true,
    value: () => {
      document.documentElement.dataset.examExitCount = String(
        Number(document.documentElement.dataset.examExitCount || 0) + 1,
      );
      Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
      document.dispatchEvent(new Event("fullscreenchange"));
      return Promise.resolve();
    },
  }));
  await page.getByRole("button", { name: "На весь экран" }).click();
  await expect(page.getByText(/Для выхода нажмите Esc/)).toBeVisible();

  const prompts: string[] = [];
  let allowExit = false;
  page.on("dialog", async (dialog) => {
    if (dialog.type() === "confirm") {
      prompts.push(dialog.message());
      if (allowExit) await dialog.accept();
      else await dialog.dismiss();
    } else await dialog.accept();
  });
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await expect(page).toHaveURL(/#\/candidate\/assessment$/);
  expect(prompts).toHaveLength(1);
  expect(prompts[0]).toContain("Покинуть оценку");
  allowExit = true;
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await expect(page.getByLabel("Ожидаемая зарплата от, руб./мес.")).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.examExitCount)).toBe("1");
  expect(prompts).toHaveLength(2);

  // Истёкшая попытка не предлагает невозможное продолжение и ведёт в историю.
  await page.getByRole("button", { name: "Оценка", exact: true }).click();
  await expect(question).toBeVisible();
  await page.clock.install();
  await page.clock.fastForward(3_601_000);
  await expect(page.getByText(/Время закончилось\. Новые ответы не принимаются/)).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(question).toHaveCount(0);
  await expect(page.getByText(/Время оценки истекло\. Вопросы больше недоступны/)).toBeVisible();
  await expect(resume).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.getByRole("button", { name: "Открыть историю" }).click();
  await expect(page.getByRole("heading", { name: "История оценок", exact: true })).toBeVisible();
  expect(prompts).toHaveLength(3);
  expect(prompts[2]).toContain("Время оценки закончилось. Сохранённые ответы останутся");
});
