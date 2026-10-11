import { test, expect } from "@playwright/test";

test("ответ поиска не сдвигает меню во время нажатия", async ({ page }) => {
  let releaseSearch!: () => void;
  const released = new Promise<void>((resolve) => {
    releaseSearch = resolve;
  });
  let held = false;
  await page.route("**/api/v1/company/searches", async (route) => {
    if (route.request().method() === "POST" && !held) {
      held = true;
      const response = await route.fetch();
      await released;
      await route.fulfill({ response });
    } else await route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  const vacancies = page.getByRole("button", { name: "Вакансии", exact: true });
  await vacancies.scrollIntoViewIfNeeded();
  const before = await vacancies.boundingBox();
  expect(before).not.toBeNull();
  await page.mouse.move(
    before!.x + before!.width / 2,
    before!.y + before!.height / 2,
  );
  await page.mouse.down();
  // Воспроизводим ответ сервера между mousedown и mouseup, без sleep/retry.
  releaseSearch();
  await expect(page.locator(".candidate-row").first()).toBeVisible();
  const after = await vacancies.boundingBox();
  expect(after).not.toBeNull();
  await page.mouse.up();
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(1);
  await expect(
    page.getByLabel("Название вакансии", { exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/#\/employer\/vacancies$/);
});

test("выбранный стек потребности сохраняется и переносится в подборку", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page.getByRole("button", { name: "Потребности", exact: true }).click();
  const title = "Стек потребности UI " + Date.now();
  await page.getByLabel("Название потребности", { exact: true }).fill(title);
  await page
    .getByLabel("Важность навыка: python", { exact: true })
    .selectOption("unused");
  await page
    .getByLabel("Важность навыка: sql", { exact: true })
    .selectOption("must");
  await page
    .getByLabel("Важность навыка: http", { exact: true })
    .selectOption("desired");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/company/needs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Сохранить потребность", exact: true })
    .click();
  expect((await saved).ok()).toBeTruthy();
  const savedData = await (await saved).json();
  expect(savedData.query.must_skills).toEqual(["sql"]);
  expect(savedData.query.desired_skills).toEqual(["http"]);
  await page.reload();
  const row = page
    .locator(".record-row")
    .filter({ has: page.getByRole("heading", { name: title, exact: true }) });
  await expect(row.getByText(/Обязательные: sql/)).toBeVisible();
  await row
    .getByRole("button", { name: "Подобрать кандидатов", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("must"))
    .toBe("sql");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("desired"))
    .toBe("http");
  await expect(page.locator(".workspace-heading")).toBeFocused();
  await page.reload();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("must"))
    .toBe("sql");
  // Явно пустой стек не должен превращаться в default python/sql при reload.
  const empty = new URL(page.url());
  empty.searchParams.set("must", "");
  empty.searchParams.set("desired", "");
  await page.goto(empty.toString());
  await expect
    .poll(() => new URL(page.url()).searchParams.get("must"))
    .toBe("");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("desired"))
    .toBe("");
});

test("контур, фокус и reduced motion доступны на узких и широких экранах", async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: /Демо-команда X/ }).click();
  await page
    .getByRole("button", { name: "Конструктор заданий", exact: true })
    .click();
  await expect(page.locator(".workspace-heading")).toBeFocused();
  await page
    .getByRole("button", { name: "Импорт материалов", exact: true })
    .click();
  const stages = page.getByRole("list", { name: "Этапы импорта" });
  await expect(stages).toBeVisible();
  await expect(stages.locator('[aria-current="step"]')).toContainText(
    "Выберите источник",
  );
  await expect(
    page
      .getByRole("navigation", { name: "Разделы кабинета" })
      .getByRole("button", { name: "Конструктор заданий", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    const movingElements = await page.evaluate(
      () =>
        [
          ...document.querySelectorAll(
            ".workspace-body, .workflow-steps, .workflow-steps li, .page-heading",
          ),
        ].filter((element) => {
          const style = getComputedStyle(element);
          return (
            style.animationName !== "none" ||
            style.transitionDuration
              .split(",")
              .some((value) => parseFloat(value) > 0)
          );
        }).length,
    );
    expect(movingElements).toBe(0);
    await page.screenshot({
      path: testInfo.outputPath("refresh-import-" + width + ".png"),
    });
  }
});
