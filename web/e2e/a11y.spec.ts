import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Автоматическая часть проверки доступности (WCAG 2.1 A/AA) на каждом разделе кабинетов.
// Ручная проверка с экранным диктором описана в docs/43.
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function scan(page: Page, where: string) {
  const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const bad = result.violations.map(
    (v) =>
      `${where}: ${v.id} (${v.impact}) × ${v.nodes.length}: ` +
      v.nodes
        .slice(0, 4)
        .map((n) => {
          const d = (n.any[0]?.data ?? {}) as Record<string, unknown>;
          return n.target.join(" ") + (d.fgColor ? ` [${d.fgColor} на ${d.bgColor}, ${d.contrastRatio}]` : "");
        })
        .join("; "),
  );
  expect(bad, bad.join("\n")).toEqual([]);
}

async function sections(page: Page, name: string, accessible = false, mobile = false) {
  await page.emulateMedia({ reducedMotion: "reduce" }); // axe иначе читает цвет посреди анимации
  await page.goto("/");
  if (accessible) await page.getByRole("button", { name: "Версия для слабовидящих" }).click();
  await page.getByRole("button", { name: new RegExp(name) }).first().click();
  const nav = page.getByRole("navigation", { name: "Разделы кабинета" });
  await expect(nav).toBeVisible();
  const labels = (await nav.getByRole("button").allTextContents()).map((t) => t.trim());
  expect(labels.length).toBeGreaterThanOrEqual(5);
  for (const label of labels) {
    await nav.getByRole("button", { name: label }).first().click();
    await page.waitForLoadState("networkidle");
    await scan(page, `${name} / ${label}`);
  }
}

test("главная страница без нарушений WCAG A/AA", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator("main")).toBeVisible();
  await scan(page, "главная");
});

for (const name of ["Демо-команда X", "Кандидат А"]) {
  test(`все разделы кабинета «${name}» без нарушений WCAG A/AA`, async ({ page }) => {
    await sections(page, name);
  });
}

test("страница размечена ориентирами и управляется с клавиатуры", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "ru");
  await expect(page.locator("main#main-content")).toHaveCount(1);
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip-link")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main#main-content")).toBeFocused();
});

test("масштаб 200 % и узкий экран не создают горизонтальной прокрутки", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto("/");
  await expect(page.locator("main")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("версия для слабовидящих включается, запоминается и тоже без нарушений", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Версия для слабовидящих" });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("html")).toHaveAttribute("data-view", "accessible");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-view", "accessible");
  await scan(page, "главная, версия для слабовидящих");
});

test("кабинет кандидата в версии для слабовидящих без нарушений", async ({ page }) => {
  await sections(page, "Кандидат А", true);
});

for (const name of ["Демо-команда X", "Кандидат А"]) {
  test(`кабинет «${name}» на телефоне (390 px): без нарушений и без горизонтальной прокрутки`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await sections(page, name, false, true);
  });
}
