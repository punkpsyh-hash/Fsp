import { test, expect } from "@playwright/test";

// Подсказка ИИ при ручной проверке открытого ответа. В стенде ИИ выключен: кнопка должна честно
// сообщить об этом, не блокируя ручную оценку. Набор готовится через API, без исполнения кода.
test("подсказка ИИ при ручной проверке не мешает ручной оценке", async ({ browser }, testInfo) => {
  test.setTimeout(90_000);
  const stamp = Date.now();
  const authorContext = await browser.newContext();
  const candidateContext = await browser.newContext();
  const login = async (context: typeof authorContext, user: string) => {
    const auth = await (
      await context.request.post("/api/v1/auth/demo-login", { data: { user_id: user } })
    ).json();
    return { "X-CSRF-Token": auth.csrf as string };
  };
  const authorHeaders = await login(authorContext, "demo-employer-x");
  const candidateHeaders = await login(candidateContext, "demo-candidate-a");

  const created = await authorContext.request.post("/api/v1/company/banks", {
    headers: authorHeaders,
    data: {
      external_id: "hint-" + stamp,
      title: "Набор для подсказки " + stamp,
      scope: "employer",
      specialization: "backend",
      grade: "junior",
      time_limit_minutes: 30,
      tasks: [
        {
          id: "open-1",
          type: "open_response",
          title: "Защита от повторов",
          prompt: "Опишите, как защитить создание приглашения от повторной отправки.",
          skills: ["http"],
          rubric:
            "0: нет решения. 50: упомянут уникальный ключ. 100: ключ привязан к автору, параметры сверяются, результат повтора сохраняется.",
          answer_limit: 4000,
        },
      ],
    },
  });
  expect(created.status()).toBe(201);
  const bank = await created.json();
  const version = bank.current_version;
  const published = await authorContext.request.post(
    `/api/v1/company/banks/${bank.id}/versions/${version.id}/publish`,
    { headers: authorHeaders, data: { revision: version.revision } },
  );
  expect(published.ok()).toBeTruthy();

  const began = await candidateContext.request.post(`/api/v1/candidate/banks/${bank.id}/attempts`, {
    headers: candidateHeaders,
    data: { version_id: version.id },
  });
  expect(began.status()).toBe(201);
  const attempt = await began.json();
  const saved = await candidateContext.request.patch(`/api/v1/candidate/bank-attempts/${attempt.id}`, {
    headers: candidateHeaders,
    data: { revision: attempt.revision, answers: { "open-1": "Синтетический ответ про уникальный ключ " + stamp } },
  });
  expect(saved.ok()).toBeTruthy();
  const done = await candidateContext.request.post(`/api/v1/candidate/bank-attempts/${attempt.id}/submit`, {
    headers: candidateHeaders,
    data: { revision: (await saved.json()).revision },
  });
  expect(done.ok()).toBeTruthy();

  const author = await authorContext.newPage();
  await author.goto("/#/employer/banks/" + bank.id);
  await author.getByRole("button", { name: "Ручная проверка", exact: true }).click();
  const review = author.locator(".record-row").filter({ hasText: "Синтетический ответ про уникальный ключ " + stamp });
  await review.getByRole("button", { name: "Подсказка ИИ по рубрике", exact: true }).click();
  await expect(author.getByRole("alert")).toContainText("ИИ выключен");
  await review.getByLabel("Оценка, от 0 до 100", { exact: true }).fill("50");
  await review.getByLabel("Обратная связь", { exact: true }).fill("Назван ключ, но нет привязки к автору.");
  await review.getByRole("button", { name: "Сохранить проверку", exact: true }).click();
  await expect(
    author.getByText("Проверка сохранена. Результат доступен кандидату", { exact: true }),
  ).toBeVisible();
  await author.screenshot({ path: testInfo.outputPath("review-hint.png"), fullPage: true });
  await authorContext.close();
  await candidateContext.close();
});
