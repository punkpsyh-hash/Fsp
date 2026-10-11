import { test, expect, type Page } from "@playwright/test";

async function login(page: Page, name: string) {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(
    page.getByRole("navigation", { name: "Разделы кабинета" }),
  ).toBeVisible();
}

// Диалог доступен только при открытом контакте: компания приглашает кандидата, кандидат принимает.
test("переписка: компания пишет после принятия приглашения, кандидат отвечает, отзыв контакта закрывает отправку", async ({
  browser,
}) => {
  test.setTimeout(90_000);
  const stamp = Date.now();
  const api = await browser.newContext();
  const employerAuth = await (
    await api.request.post("/api/v1/auth/demo-login", {
      data: { user_id: "demo-employer-x" },
    })
  ).json();
  const candidateApi = await browser.newContext();
  const candidateAuth = await (
    await candidateApi.request.post("/api/v1/auth/demo-login", {
      data: { user_id: "demo-candidate-a" },
    })
  ).json();
  // Чистое состояние: прежний контакт отозван, затем создано новое приглашение.
  await candidateApi.request.delete("/api/v1/candidate/contacts/demo-employer-x", {
    headers: { "X-CSRF-Token": candidateAuth.csrf },
  });
  const invited = await api.request.post("/api/v1/company/invitations", {
    headers: {
      "Idempotency-Key": "e2e-chat-" + stamp,
      "X-CSRF-Token": employerAuth.csrf,
    },
    data: {
      candidate_id: "demo-candidate-a",
      description: "Предложение для проверки переписки " + stamp,
      salary_from: 120000,
      salary_to: 180000,
      salary_basis: "gross",
    },
  });
  expect(invited.ok()).toBeTruthy();

  const candidatePage = await (await browser.newContext()).newPage();
  await login(candidatePage, "Кандидат А");
  await candidatePage.goto("/#/candidate/offers");
  await candidatePage
    .getByRole("button", { name: "Принять и открыть контакт" })
    .first()
    .click();
  await expect(
    candidatePage.getByRole("button", { name: "Написать сообщение" }).first(),
  ).toBeVisible();

  const employerPage = await (await browser.newContext()).newPage();
  await login(employerPage, "Демо-команда X");
  await employerPage.goto("/#/employer/messages");
  await employerPage.getByRole("button", { name: /Кандидат P-/ }).click();
  const ask = "Приглашаем на интервью в четверг " + stamp;
  await employerPage.getByLabel("Сообщение", { exact: true }).fill(ask);
  await employerPage.getByRole("button", { name: "Отправить" }).click();
  const employerLog = employerPage.getByRole("log", { name: "История сообщений" });
  await expect(employerLog).toContainText(ask);

  // Кандидат видит число непрочитанных и открывает диалог.
  await candidatePage.goto("/#/candidate/messages");
  await candidatePage.reload();
  await expect(
    candidatePage.getByRole("navigation", { name: "Разделы кабинета" }),
  ).toContainText(/Сообщения \(\d+\)/);
  await candidatePage.getByRole("button", { name: /Демо-команда X|Компания/ }).first().click();
  const candidateLog = candidatePage.getByRole("log", { name: "История сообщений" });
  await expect(candidateLog).toContainText(ask);
  const reply = "Спасибо, четверг подходит " + stamp;
  await candidatePage.getByLabel("Сообщение", { exact: true }).fill(reply);
  await candidatePage.getByRole("button", { name: "Отправить" }).click();
  await expect(candidateLog).toContainText(reply);

  // Отзыв контакта: история остаётся, поле отправки исчезает.
  const revoked = await candidateApi.request.delete(
    "/api/v1/candidate/contacts/demo-employer-x",
    { headers: { "X-CSRF-Token": candidateAuth.csrf } },
  );
  expect(revoked.status()).toBe(204);
  await candidatePage.reload();
  await expect(candidateLog).toContainText(ask);
  await expect(candidatePage.getByText("Контакт отозван или закрыт")).toBeVisible();
  await expect(candidatePage.getByLabel("Сообщение", { exact: true })).toHaveCount(0);
});
