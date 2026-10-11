import { test, expect } from "@playwright/test";

test("интерактивное объяснение меняет порядок и применяет обязательный фильтр", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const example = page.getByRole("region", { name: "Один профиль. Разные потребности." });
  await expect(example).toContainText("это не выдача API");
  const ranking = example.getByRole("list", { name: "Порядок вымышленных профилей" });
  await expect(ranking.locator("li").first()).toContainText("Пример А");
  await example.getByRole("button", { name: "Тестирование", exact: true }).click();
  await expect(ranking.locator("li").first()).toContainText("Пример Б");
  await example.getByLabel("Тестирование обязательно", { exact: true }).check();
  await expect(ranking.locator("li")).toHaveCount(1);
  await expect(example.locator(".showcase-excluded")).toContainText("Пример А · исключён");
  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
});

test("сравнение сохраняет выбранных на страницах, ограничивает три и сбрасывается с новой подборкой", async ({ page }) => {
  const rows = Array.from({ length: 9 }, (_, index) => ({
    id: `contest-fixture-${index}`, alias: `COMPARE-${index + 1}`, specialization: "backend",
    confirmed_grade: "junior", skills: ["python", "sql"], formats: ["remote"],
    salary_min: 100000, test_score: 80, fsp_state: "none", fsp_evidence: [],
    score: 77 - index, missing: ["http"], fsp_bonus: 0,
    components: { assessment: 36, skills: 35 - index, fsp: 0, freshness: 6 },
  }));
  await page.route("**/api/v1/company/searches", (route) => route.request().method() !== "POST"
    ? route.continue() : route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "comparison-fixture", rows }) }));
  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page.getByRole("button", { name: "Банк кандидатов", exact: true }).click();
  const candidates = page.locator(".candidate-row");
  await expect(candidates).toHaveCount(8);
  await candidates.nth(0).getByRole("button", { name: "Сравнить", exact: true }).click();
  await candidates.nth(1).getByRole("button", { name: "Сравнить", exact: true }).click();
  const pages = page.getByRole("navigation", { name: "Страницы: Результаты подбора" });
  await pages.getByRole("button", { name: /Следующая страница/ }).click();
  await candidates.first().getByRole("button", { name: "Сравнить", exact: true }).click();
  const comparison = page.getByRole("region", { name: "Сравнение кандидатов", exact: true });
  await expect(comparison.locator(".comparison-profile")).toHaveCount(3);
  await expect(comparison).toContainText("COMPARE-1");
  await expect(comparison).toContainText("COMPARE-9");
  await expect(comparison).toContainText("36.00 / 45");
  await expect(comparison).toContainText("http");
  await expect(comparison).not.toContainText("@example.invalid");
  await pages.getByRole("button", { name: /Предыдущая страница/ }).click();
  await expect(candidates.nth(2).getByRole("button", { name: "Сравнить", exact: true })).toBeDisabled();
  await comparison.getByRole("button", { name: "Убрать COMPARE-9 из сравнения", exact: true }).click();
  await expect(candidates.nth(2).getByRole("button", { name: "Сравнить", exact: true })).toBeEnabled();
  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(comparison).toHaveCount(0);
});

test("ошибка загрузки разбора не теряет сохранённый результат и допускает повтор", async ({ page }) => {
  const report = {
    threshold: 70, correct: 1, total: 1, needed_correct: 1,
    skills: [{ skill: "sql", correct: 1, total: 1, score: 100, status: "strong", topics: ["NULL"], recommendation: "Закрепите COUNT(email) и NULL." }],
    questions: [{ id: "saved-count", skill: "sql", status: "correct", selected_answer: "13", correct_answer: "13", explanation: "COUNT(email) исключает NULL: 17 − 4 = 13." }],
  };
  let requests = 0;
  await page.route("**/api/v1/assessments/attempts/contest-report-fixture", (route) => {
    requests++;
    if (requests === 2) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "temporary", message: "Синтетическая ошибка сети" }) });
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({
      id: "contest-report-fixture", grade: "junior", specialization: "backend", answers: { "saved-count": "13" },
      questions: [{ id: "saved-count", skill: "sql", title: "17 строк, 4 NULL. Чему равен COUNT(email)?", options: ["13", "17"] }],
      result: { score: 100, skills: ["sql"], passed: true, limitation: "Синтетический тест восстановления." },
      feedback: requests === 1 ? null : report,
    }) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Кандидат А/ }).click();
  await expect(page.getByRole("navigation", { name: "Разделы кабинета" })).toBeVisible();
  await page.goto("/#/candidate/assessment/contest-report-fixture");
  await expect(page.getByText("Оценочная форма пройдена", { exact: true })).toBeVisible();
  const region = page.getByRole("region", { name: "Разбор оценки", exact: true });
  await expect(region.getByRole("alert")).toContainText("Результат оценки сохранён");
  await region.getByRole("button", { name: "Повторить загрузку разбора", exact: true }).click();
  await expect(region.getByText("1 из 1 верно", { exact: true })).toBeVisible();
  await expect(page.getByRole("radio", { name: "13", exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: "13", exact: true })).toBeDisabled();
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
});
