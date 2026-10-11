import { test, expect } from "@playwright/test";

type SyntheticCandidate = {
  id: string;
  alias: string;
  specialization: string;
  confirmed_grade: string;
  skills: string[];
  formats: string[];
  salary_min: number;
  test_score: number;
  assessed_at: string;
  fsp_state: string;
  fsp_evidence: { event: string; discipline: string; place: number; source: string; date: string; role: string }[];
  activity_at: string;
  experience: { years_experience: number; roles: string[]; soft_skills: string[] };
  score: number;
  matched: string[];
  missing: string[];
  fsp_bonus: number;
  demo: true;
};

function candidates(count: number, specialization = "backend") {
  return Array.from({ length: count }, (_, index): SyntheticCandidate => {
    const number = index + 1;
    const verified = number % 3 === 0;
    return {
      id: `pagination-fixture-${specialization}-${number}`,
      alias: `PAGE-${String(number).padStart(3, "0")}`,
      specialization,
      confirmed_grade: "junior",
      skills: [specialization === "frontend" ? "javascript" : "python"],
      formats: ["remote"],
      salary_min: 100_000 + number,
      test_score: 80,
      assessed_at: "2026-10-01T00:00:00Z",
      fsp_state: verified ? "verified" : "none",
      fsp_evidence: verified
        ? [{ event: "Синтетический турнир", discipline: "Алгоритмы", place: 3, source: "local-mock", date: "2026-09-01", role: "Участник команды" }]
        : [],
      activity_at: "2026-10-02T00:00:00Z",
      experience: { years_experience: 1, roles: ["Разработчик"], soft_skills: ["Коммуникация"] },
      score: 90 - index / 10,
      matched: [specialization === "frontend" ? "javascript" : "python"],
      missing: [],
      fsp_bonus: verified ? 8 : 0,
      demo: true,
    };
  });
}

test("длинная mock-почта показывает письмо текущего адреса первым и сохраняет границы страниц", async ({ page }) => {
  const currentEmail = "new-candidate@example.invalid";
  const mails = Array.from({ length: 22 }, (_, index) => {
    const number = index + 1;
    return {
      id: `mail-fixture-${String(number).padStart(3, "0")}`,
      email: `mail-${String(number).padStart(3, "0")}@example.invalid`,
      token: `SYNTHETIC-MOCK-TOKEN-${number}`,
      expires_at: new Date(Date.UTC(2026, 9, 7, number)).toISOString(),
    };
  });
  // Intentionally put the current address last and older than all other mail.
  mails.push({
    id: "mail-fixture-current",
    email: currentEmail,
    token: "SYNTHETIC-MOCK-TOKEN-CURRENT",
    expires_at: "2026-09-01T00:00:00.000Z",
  });
  await page.route("**/api/v1/auth/mock-mail", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(mails),
    }),
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Mock-почта", exact: true }).click();
  const pages = page.getByRole("navigation", {
    name: "Страницы: Письма демонстрационного ящика",
  });
  const rows = page.locator(".mail-row");
  await expect(pages.getByRole("status")).toContainText("1–8 из 23 · страница 1 из 3");
  await expect(rows).toHaveCount(8);
  await expect(rows.first()).toContainText(currentEmail);
  await expect(rows.nth(1)).toContainText("mail-022@example.invalid");
  await expect(pages.getByRole("button", { name: /Предыдущая страница/ })).toBeDisabled();
  await expect(page.locator("body")).not.toContainText("SYNTHETIC-MOCK-TOKEN");

  await pages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(pages.getByRole("status")).toContainText("9–16 из 23 · страница 2 из 3");
  await expect(rows).toHaveCount(8);
  await expect(rows.first()).toContainText("mail-015@example.invalid");
  await pages.getByRole("button", { name: /^Страница 3:/ }).click();
  await expect(pages.getByRole("status")).toContainText("17–23 из 23 · страница 3 из 3");
  await expect(rows).toHaveCount(7);
  await expect(rows.first()).toContainText("mail-007@example.invalid");
  await expect(rows.last()).toContainText("mail-001@example.invalid");
  await expect(pages.getByRole("button", { name: /Следующая страница/ })).toBeDisabled();
  await pages.getByRole("button", { name: /Предыдущая страница/ }).click();
  await expect(pages.getByRole("status")).toContainText("9–16 из 23 · страница 2 из 3");

  await page.setViewportSize({ width: 320, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test("длинная подборка сохраняет границы страниц и сбрасывается после смены фильтра и специализации", async ({ page }) => {
  await page.route("**/api/v1/company/searches", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const query = route.request().postDataJSON() as {
      specialization: string;
      fsp_only: boolean;
    };
    const total = query.specialization === "frontend" ? 4 : 23;
    let rows = candidates(total, query.specialization);
    if (query.fsp_only) rows = rows.filter((row) => row.fsp_state === "verified");
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "pagination-fixture-search",
        candidate_ids: rows.map((row) => row.id),
        rows,
        created_at: "2026-10-07T00:00:00Z",
        algorithm_version: "e2e-fixture-v1",
        demo: true,
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page.getByRole("button", { name: "Банк кандидатов", exact: true }).click();

  const pages = page.getByRole("navigation", {
    name: "Страницы: Результаты подбора",
  });
  const rows = page.locator(".candidate-row");
  await expect(pages).toBeVisible();
  await expect(pages.getByRole("status")).toContainText("1–8 из 23 · страница 1 из 3");
  await expect(rows).toHaveCount(8);
  await expect(rows.first().getByRole("heading", { name: "PAGE-001", exact: true })).toBeVisible();
  await expect(pages.getByRole("button", { name: /Предыдущая страница/ })).toBeDisabled();

  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }

  const nextPage = pages.getByRole("button", { name: /Следующая страница/ });
  await nextPage.focus();
  await page.keyboard.press("Enter");
  await expect(pages.getByRole("status")).toContainText("9–16 из 23 · страница 2 из 3");
  await expect(pages.getByRole("button", { name: /^Страница 2:/ })).toBeDisabled();
  await expect(rows.first().getByRole("heading", { name: "PAGE-009", exact: true })).toBeVisible();
  await pages.getByRole("button", { name: /^Страница 3:/ }).click();
  await expect(pages.getByRole("status")).toContainText("17–23 из 23 · страница 3 из 3");
  await expect(rows).toHaveCount(7);
  await expect(rows.last().getByRole("heading", { name: "PAGE-023", exact: true })).toBeVisible();
  await expect(pages.getByRole("button", { name: /Следующая страница/ })).toBeDisabled();
  await pages.getByRole("button", { name: /Предыдущая страница/ }).click();
  await expect(pages.getByRole("status")).toContainText("9–16 из 23 · страница 2 из 3");
  await expect(rows.first().getByRole("heading", { name: "PAGE-009", exact: true })).toBeVisible();
  await pages.getByRole("button", { name: /Следующая страница/ }).click();

  // Новый source/query с меньшим набором не должен оставлять пользователя на пустой странице 3.
  await page.getByLabel("Специализация", { exact: true }).selectOption("frontend");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(pages.getByRole("status")).toContainText("1–4 из 4 · страница 1 из 1");
  await expect(rows).toHaveCount(4);
  await expect(rows.first().getByRole("heading", { name: "PAGE-001", exact: true })).toBeVisible();
  await expect(pages.getByRole("button", { name: /Предыдущая страница/ })).toBeDisabled();
  await expect(pages.getByRole("button", { name: /Следующая страница/ })).toBeDisabled();

  await page.getByLabel("Специализация", { exact: true }).selectOption("backend");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(pages.getByRole("status")).toContainText("страница 1 из 3");
  await pages.getByRole("button", { name: /^Страница 3:/ }).click();
  await expect(pages.getByRole("status")).toContainText("страница 3 из 3");
  await page.getByLabel("Только с достижениями ФСП · mock", { exact: true }).check();
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(pages.getByRole("status")).toContainText("1–7 из 7 · страница 1 из 1");
  await expect(rows).toHaveCount(7);
  await expect(rows.first()).toContainText("Демо-история подтверждена");
});

test("история подборок загружается серверными страницами и сохраняет состояние при ошибке", async ({ page }) => {
  const requestedOffsets: number[] = [];
  let failSecondPageOnce = true;
  const historyItems = Array.from({ length: 23 }, (_, index) => {
    const number = 23 - index;
    return {
      id: `history-${String(number).padStart(3, "0")}`,
      created_at: `2026-10-${String(Math.max(1, number % 28)).padStart(2, "0")}T00:00:00Z`,
      query: {
        specialization: number === 1 ? "frontend" : "backend",
        grade: "junior",
        format: "remote",
        salary_to: number === 1 ? 234567 : 150000 + number,
        must_skills: [number === 1 ? "javascript" : "python"],
        desired_skills: ["http"],
        fsp_only: false,
      },
    };
  });

  await page.route("**/api/v1/company/searches/page**", async (route) => {
    const requestUrl = new URL(route.request().url());
    const offset = Number(requestUrl.searchParams.get("offset"));
    const limit = Number(requestUrl.searchParams.get("limit"));
    requestedOffsets.push(offset);
    if (offset === 8 && failSecondPageOnce) {
      failSecondPageOnce = false;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ message: "Синтетическая ошибка страницы истории" }),
      });
    }
    const items = historyItems.slice(offset, offset + limit);
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items, total: historyItems.length, offset, limit }),
    });
  });
  await page.route("**/api/v1/company/searches", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: "fixture-search", rows: [], candidate_ids: [], demo: true }),
    });
  });
  await page.route("**/api/v1/company/searches/history-001", async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "history-001",
        query: historyItems.at(-1)!.query,
        rows: [],
      }),
    }),
  );

  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page.getByRole("button", { name: "Банк кандидатов", exact: true }).click();
  const historyPages = page.getByRole("navigation", {
    name: "Страницы: История подборок",
  });
  await expect(historyPages.getByRole("status")).toContainText("1–8 из 23 · страница 1 из 3");
  await expect.poll(() => requestedOffsets).toContain(0);

  await historyPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(page.getByRole("alert")).toContainText("Синтетическая ошибка страницы истории");
  await expect(historyPages.getByRole("status")).toContainText("1–8 из 23 · страница 1 из 3");
  await expect(historyPages.getByRole("button", { name: /Предыдущая страница/ })).toBeDisabled();
  await historyPages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(historyPages.getByRole("status")).toContainText("9–16 из 23 · страница 2 из 3");
  await expect.poll(() => requestedOffsets.filter((offset) => offset === 8).length).toBe(2);
  await historyPages.getByRole("button", { name: /^Страница 3:/ }).click();
  await expect(historyPages.getByRole("status")).toContainText("17–23 из 23 · страница 3 из 3");
  await expect.poll(() => requestedOffsets).toContain(16);

  await page.getByLabel("Сохранённые подборки").selectOption("history-001");
  await expect(page.getByLabel("Специализация", { exact: true })).toHaveValue("frontend");
  await expect(page.getByLabel("Бюджет до, руб.", { exact: true })).toHaveValue("234567");
});

test("ключевые страницы не переполняют viewport при клавиатурном переходе и reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page.getByRole("button", { name: "Конструктор заданий", exact: true }).click();
  await expect(page.locator(".workspace-heading")).toBeFocused();

  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: test.info().outputPath(`constructor-${width}.png`), fullPage: true });
  }
});
