import { test, expect, type Page } from "@playwright/test";

test.beforeAll(async ({}, info) => {
  if (info.project.name !== "chromium") {
    test.setTimeout(70000);
    await new Promise(resolve => setTimeout(resolve, 61000));
  }
});

async function createDraft(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page.getByRole("button", { name: "Конструктор заданий", exact: true }).click();
  await page.getByLabel("Название нового набора").fill("Генерация E2E " + Date.now());
  await page.getByRole("button", { name: "Создать набор", exact: true }).click();
  await expect(page).toHaveURL(/#\/employer\/banks\//);
  await page.getByLabel("Тип нового задания").selectOption("open_response");
  await page.getByLabel("Контекст задания для ИИ").fill("Обработка повторной доставки событий в очереди");
  return page.url().split("/banks/")[1];
}

test("выключенная модель не подменяется готовым ИИ-заданием", async ({ page }) => {
  await createDraft(page);
  await page.getByRole("button", { name: "Предложить задание с ИИ", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("ИИ-генерация выключена");
  await expect(page.getByRole("button", { name: "Добавить предложение в черновик" })).toHaveCount(0);
  await expect(page.getByText("Первое задание задаёт тон", { exact: true })).toBeVisible();
});

test("автор видит рубрику и явно добавляет предложение в черновик до отдельной публикации", async ({ page }, testInfo) => {
  const bankId = await createDraft(page);
  await page.route("**/suggest-task", async route => {
    const body = route.request().postDataJSON();
    expect(body.kind).toBe("open_response");
    await route.fulfill({ json: {
      source: "llm-mock", model: "browser-demo", checks: ["json-schema"], review_required: true,
      task: { id: "suggestion-demo", type: "open_response", title: "Повторная доставка событий",
        prompt: "Опишите обработку повторной доставки события, чтобы запись в хранилище не дублировалась.",
        skills: ["python"], family: "queue-demo", weight: 1, expected_minutes: 5,
        options: [], answer_key: [], numeric_answer: null, partial_credit: false,
        absolute_tolerance: 0, relative_tolerance: 0, unit: "", answer_limit: 4000,
        rubric: "0: нет проверки повтора. 50: указан уникальный ключ. 100: ключ и атомарная обработка.",
        language: null, starter_code: "", examples: [], hidden_tests: [],
        runtime_limits: { wall_seconds: 3, memory_mb: 512 } }
    } });
  });
  await page.getByRole("button", { name: "Предложить задание с ИИ", exact: true }).click();
  await expect(page.getByText("Демонстрационный образец, без вызова модели", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Рубрика:/)).toContainText("атомарная обработка");
  const checkbox = page.getByLabel("Я проверил условие и эталон или рубрику");
  const checkboxBox = await checkbox.boundingBox();
  expect(checkboxBox).not.toBeNull();
  expect(checkboxBox!.width).toBeLessThanOrEqual(25);
  if (testInfo.project.name === "chromium") {
    await page.screenshot({ path: testInfo.outputPath("suggestion-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("suggestion-mobile.png"), fullPage: true });
  }
  const before = await page.request.get(`/api/v1/company/banks/${bankId}`);
  expect((await before.json()).current_version.tasks).toHaveLength(0);
  const add = page.getByRole("button", { name: "Добавить предложение в черновик", exact: true });
  await expect(add).toBeDisabled();
  await page.getByLabel("Я проверил условие и эталон или рубрику").check();
  const saved = page.waitForResponse(r => r.url().includes(`/company/banks/${bankId}/versions/`) && r.request().method() === "PATCH");
  await add.click();
  expect((await saved).ok()).toBeTruthy();
  const after = await page.request.get(`/api/v1/company/banks/${bankId}`);
  const version = (await after.json()).current_version;
  expect(version.state).toBe("draft");
  expect(version.tasks).toHaveLength(1);
  expect(version.tasks[0].rubric).toContain("атомарная обработка");
  await page.getByLabel("Тип нового задания").selectOption("code");
  await expect(page.getByText(/для ИИ-генерации нужен отдельный прогон/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Предложить задание с ИИ", exact: true })).toHaveCount(0);
});

test("ожидание модели удерживает черновик и показывает ошибку после задержки", async ({ page }) => {
  await createDraft(page);
  let release!: () => void;
  let announce!: () => void;
  const barrier = new Promise<void>((resolve) => { release = resolve; });
  const started = new Promise<void>((resolve) => { announce = resolve; });
  await page.route("**/suggest-task", async (route) => {
    announce();
    await barrier;
    await route.fulfill({ status: 503, json: { detail: "Модель временно недоступна" } });
  });
  const address = page.url();
  await page.getByRole("button", { name: "Предложить задание с ИИ", exact: true }).click();
  await started;
  await expect(page.getByText("Модель готовит предложение. Дождитесь ответа перед сменой раздела.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ручная проверка" })).toBeDisabled();
  await expect(page.getByLabel("Открыть версию")).toBeDisabled();
  await expect(page.getByLabel("Тип нового задания")).toBeDisabled();
  await page.getByRole("button", { name: "Конструктор заданий", exact: true }).click();
  await expect(page).toHaveURL(address);
  release();
  await expect(page.getByRole("alert")).toContainText("Модель временно недоступна");
  await expect(page.getByRole("button", { name: "Ручная проверка" })).toBeEnabled();
  await expect(page.getByText("Модель готовит предложение. Дождитесь ответа перед сменой раздела.")).toHaveCount(0);
});
