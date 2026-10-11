import { expect, test } from "@playwright/test";

test("мокированный weekly offer виден в профиле и первым в списке из девяти заданий", async ({ page }) => {
  // Управляемый ответ проверяет только UI-контракт; серверный отбор проверяет tests/test_weekly_tasks.py.
  const tasks = Array.from({ length: 9 }, (_, index) => ({
    id: `weekly-browser-${index + 1}`,
    title: `Синтетическая задача ${index + 1}`,
    description: "Опишите проверку доступа к синтетическому API после отзыва разрешения.",
    rubric: "Проверить отрицательный сценарий и повторную отправку.",
    specialization: "backend",
    grade: "junior",
    published: true,
    company: { name: "Демо-команда X" },
  }));
  const recommended = tasks[8];
  let offerVisible = true;
  await page.route("**/api/v1/candidate/tasks", (route) => route.fulfill({ json: {
    available: offerVisible ? tasks : [],
    next_at: "2026-10-12T00:00:00Z",
    responses: [],
    recommendation: offerVisible ? {
      id: "weekly-browser-offer",
      task: recommended,
      period_starts_at: "2026-10-05T00:00:00Z",
      next_period_at: "2026-10-12T00:00:00Z",
    } : null,
    recommendation_state: offerVisible ? "offered" : "cooldown",
  } }));

  await page.goto("/");
  await page.getByRole("button", { name: /Кандидат А/ }).click();
  const notice = page.getByRole("region", { name: "Предложение задания на неделю" });
  await expect(notice).toBeVisible();
  await expect(notice).toContainText(recommended.title);
  await expect(notice).toContainText("не меняет глобальный грейд");
  await notice.getByRole("button", { name: "Открыть предложенное задание" }).click();
  await expect(page).toHaveURL(/#\/candidate\/tasks$/);
  await expect(page.locator("article.record-row").first().getByRole("heading", { name: recommended.title })).toBeVisible();
  await expect(page.getByText("Предложение этой недели:")).toContainText(recommended.title);

  offerVisible = false;
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await expect(notice).toHaveCount(0);
});

test("задержанный и ошибочный GET не показывает ложную дату или вывод о грейде", async ({ page }) => {
  await page.goto("/");
  const profileTasks = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/candidate/tasks") && response.request().method() === "GET");
  await page.getByRole("button", { name: /Кандидат А/ }).click();
  await expect(page.getByRole("heading", { name: "Профиль и анкета" })).toBeVisible();
  await profileTasks;

  let release!: () => void;
  let announce!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const started = new Promise<void>((resolve) => { announce = resolve; });
  let requests = 0;
  // Здесь ответы GET управляемые: проверяется только UI загрузки и повтора.
  await page.route("**/api/v1/candidate/tasks", async (route) => {
    requests += 1;
    if (requests === 1) {
      announce();
      await gate;
      await route.fulfill({ status: 503, json: { detail: "Список заданий временно недоступен" } });
    } else {
      await route.fulfill({ json: {
        available: [], next_at: "2026-10-12T00:00:00Z", responses: [],
        recommendation: null, recommendation_state: "cooldown",
      } });
    }
  });
  await page.getByRole("button", { name: "Короткие задания", exact: true }).click();
  await started;
  await expect(page.getByRole("status").filter({ hasText: "Загрузка коротких заданий" })).toBeVisible();
  await expect(page.getByText(/Invalid Date|Для получения задач подтвердите грейд|Следующее короткое задание станет доступно/)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "История коротких заданий" })).toHaveCount(0);

  release();
  await expect(page.getByRole("alert")).toContainText("Список заданий временно недоступен");
  await expect(page.getByRole("button", { name: "Повторить загрузку заданий" })).toBeVisible();
  await expect(page.getByText(/Invalid Date|Для получения задач подтвердите грейд|Следующее короткое задание станет доступно/)).toHaveCount(0);
  await page.getByRole("button", { name: "Повторить загрузку заданий" }).click();
  await expect(page.getByText(/Следующее короткое задание станет доступно/)).toBeVisible();
  await expect(page.getByText(/Invalid Date|Для получения задач подтвердите грейд/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Повторить загрузку заданий" })).toHaveCount(0);
  expect(requests).toBe(2);
});
