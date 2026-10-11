import { test, expect, type Page } from "@playwright/test";

const catalog = {
  declared_skills: [
    { id: "python", label: "Python", specializations: ["backend"] },
    { id: "docker", label: "Docker", specializations: ["backend", "qa"] },
    { id: "kubernetes", label: "Kubernetes", specializations: ["backend"] },
    { id: "javascript", label: "JavaScript", specializations: ["frontend"] },
  ],
  work_tasks: [
    {
      id: "api-development",
      label: "Разработка API · демо-проверка",
      description: "Проверка Python и HTTP на ограниченной форме.",
      skills: ["python", "http"],
      specialization: "backend",
    },
    {
      id: "http-client",
      label: "HTTP-клиент · демо-проверка",
      description: "Проверка обработки ответов.",
      skills: ["javascript", "http"],
      specialization: "frontend",
    },
  ],
  work_tasks_version: "team-work-v1",
};
const evidence = {
  declared: ["docker"],
  assessment: [
    {
      skill: "python",
      score: 75,
      correct: 3,
      total: 4,
      version: "scenarios-v5",
      assessed_at: "2026-10-08T00:00:00Z",
      source: "assessment",
    },
  ],
  practice: [
    {
      skill: "sql",
      score: 60,
      tasks: 1,
      total_tasks: 2,
      completed_at: "2026-10-07T00:00:00Z",
      source: "employer-practice",
    },
  ],
  limitations: ["Независимой калибровки нет."],
};
const baseQuery = {
  specialization: "backend",
  grade: "junior",
  format: "remote",
  salary_to: 200000,
  must_skills: ["python"],
  desired_skills: ["sql"],
  fsp_only: false,
};
async function mockSession(page: Page, role: "candidate" | "employer") {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const value = path.endsWith("/me")
      ? {
          id: `skills-${role}`,
          label: "Синтетический участник",
          role,
          csrf: "synthetic-csrf",
        }
      : path.endsWith("/catalog")
        ? catalog
        : path.endsWith("/company/searches/page")
          ? { items: [], total: 0, offset: 0, limit: 8 }
          : [];
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(value),
    });
  });
}
async function noOverflow(page: Page) {
  for (const width of [320, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  }
}

test("заявленные технологии сохраняются после reload отдельно от оценки и практики", async ({
  page,
}) => {
  await mockSession(page, "candidate");
  await page.emulateMedia({ reducedMotion: "reduce" });
  let profile = {
    id: "skills-owner",
    alias: "SKILL-OWNER",
    specialization: "backend",
    claimed_grade: "junior",
    confirmed_grade: "junior",
    salary_min: 100000,
    formats: ["remote"],
    contact: "synthetic@example.invalid",
    published: true,
    skills: ["python"],
    test_score: 75,
    fsp_state: "none",
    fsp_member_id: null,
    fsp_evidence: [],
    contact_grants: [],
    resume: {
      full_name: "Синтетический кандидат",
      years_experience: 1,
      declared_skills: ["docker"],
      roles: [],
      soft_skills: [],
      education: "",
      about: "Скрытая анкета",
    },
    skill_evidence: structuredClone(evidence),
  };
  let saved: any;
  await page.route("**/api/v1/candidate/profile", async (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
      profile = {
        ...profile,
        ...saved,
        skill_evidence: {
          ...profile.skill_evidence,
          declared: saved.resume.declared_skills,
        },
      };
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(profile),
    });
  });
  await page.goto("/#/candidate/profile");
  const declared = page.getByRole("group", {
    name: "Заявленные технологии",
    exact: true,
  });
  await expect(declared.getByLabel("Docker", { exact: true })).toBeChecked();
  await declared.getByLabel("Python", { exact: true }).check();
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Профиль сохранён");
  expect(saved.resume.declared_skills).toEqual(["docker", "python"]);
  expect(saved.skills).toBeUndefined();
  await page.reload();
  await expect(declared.getByLabel("Python", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("Docker", { exact: true })).toBeChecked();
  const sources = page.locator(".skill-evidence");
  await expect(sources).toContainText("3 из 4 ответов");
  await expect(sources).toContainText("scenarios-v5");
  await expect(sources).toContainText("задач ≥50% / всего оценённых: 1/2");
  await expect(sources).toContainText("практика работодателя");
  await expect(sources).toContainText("не повышает глобальный грейд");
  await expect(page.locator(".evidence").first()).toContainText(
    "Junior · оценка 75/100 · python",
  );
  await noOverflow(page);
});

test("импорт PDF добавляет только разрешённые технологии и сохраняет ручной выбор после reload", async ({
  page,
}) => {
  await mockSession(page, "candidate");
  let catalogReleased = false;
  let releaseCatalog = () => {};
  const catalogGate = new Promise<void>((resolve) => {
    releaseCatalog = () => {
      catalogReleased = true;
      resolve();
    };
  });
  await page.route("**/api/v1/catalog", async (route) => {
    if (!catalogReleased) await catalogGate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(catalog),
    });
  });
  let profile = {
    id: "pdf-stack-owner",
    alias: "PDF-STACK-OWNER",
    specialization: "backend",
    claimed_grade: "junior",
    confirmed_grade: "junior",
    salary_min: 100000,
    formats: ["remote"],
    contact: "before-import@example.invalid",
    published: false,
    skills: [],
    test_score: 0,
    fsp_state: "none",
    fsp_member_id: null,
    fsp_evidence: [],
    contact_grants: [],
    resume: {
      full_name: "Ручное имя",
      years_experience: 1,
      declared_skills: ["python"],
      roles: [],
      soft_skills: [],
      education: "",
      about: "",
    },
    skill_evidence: { ...evidence, declared: ["python"] },
  };
  let saved: any;
  await page.route("**/api/v1/candidate/profile", async (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
      profile = { ...profile, ...saved };
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(profile),
    });
  });
  let releasePreview = () => {};
  let markPreviewRequested = () => {};
  const previewRequested = new Promise<void>((resolve) => {
    markPreviewRequested = resolve;
  });
  const previewGate = new Promise<void>((resolve) => {
    releasePreview = resolve;
  });
  await page.route("**/api/v1/candidate/resume-preview", async (route) => {
    markPreviewRequested();
    await previewGate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        resume: {
          full_name: "Импортированный кандидат",
          years_experience: 2,
          declared_skills: ["unknown-from-resume"],
          roles: [],
          soft_skills: [],
          education: "",
          about: "Стек извлечён из PDF",
        },
        contact: "imported@example.invalid",
        specialization: "backend",
        claimed_grade: "junior",
        claimed_skills: ["docker", "javascript", "unknown-claimed", "docker"],
        warnings: [],
      }),
    });
  });

  await page.goto("/#/candidate/profile");
  const pdfImport = page.getByLabel("Импорт текстового PDF · до 2 МБ");
  await expect(pdfImport).toBeDisabled();
  await expect(
    page.getByText("Импорт PDF станет доступен после загрузки."),
  ).toBeVisible();
  releaseCatalog();
  await expect(pdfImport).toBeEnabled();
  await pdfImport.setInputFiles({
    name: "synthetic-resume.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 synthetic browser fixture"),
  });
  await previewRequested;
  const declared = page.getByRole("group", {
    name: "Заявленные технологии",
    exact: true,
  });
  await declared.getByLabel("Kubernetes", { exact: true }).check();
  await page
    .getByLabel("Скрытый контакт · только example.invalid")
    .fill("edited-during-preview@example.invalid");
  releasePreview();
  await expect(page.getByText("Поля ниже — предложения из PDF.")).toBeVisible();
  await expect(declared.getByLabel("Docker", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("Python", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("Kubernetes", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("JavaScript", { exact: true })).toBeChecked();
  await expect(
    page.getByLabel("Скрытый контакт · только example.invalid"),
  ).toHaveValue("edited-during-preview@example.invalid");
  await expect(page.getByLabel("Имя синтетического кандидата")).toHaveValue(
    "Импортированный кандидат",
  );
  await page
    .getByRole("button", { name: "Сохранить профиль", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Профиль сохранён");
  expect(saved.contact).toBe("edited-during-preview@example.invalid");
  expect(saved.resume.declared_skills).toEqual([
    "python",
    "kubernetes",
    "docker",
    "javascript",
  ]);
  expect(saved.resume.declared_skills).not.toContain("unknown-from-resume");
  expect(saved.resume.declared_skills).not.toContain("unknown-claimed");

  await page.reload();
  await expect(declared.getByLabel("Docker", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("Python", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("Kubernetes", { exact: true })).toBeChecked();
  await expect(declared.getByLabel("JavaScript", { exact: true })).toBeChecked();
  await expect(
    page.getByLabel("Скрытый контакт · только example.invalid"),
  ).toHaveValue("edited-during-preview@example.invalid");
});

test("задачи дополняют желательные условия, сохраняются в URL и истории через страницы; сравнение показывает пробелы без контактов", async ({
  page,
}) => {
  await mockSession(page, "employer");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const savedQuery = { ...baseQuery, work_tasks: ["api-development"] };
  const rows = Array.from({ length: 9 }, (_, index) => ({
    id: `skills-row-${index}`,
    alias: `SKILLS-${index + 1}`,
    specialization: "backend",
    confirmed_grade: "junior",
    salary_min: 100000,
    formats: ["remote"],
    skills: ["python"],
    test_score: 75,
    fsp_state: "none",
    fsp_evidence: [],
    score: 60,
    missing: ["http", "sql"],
    components: { assessment: 33.75, skills: 17.5, fsp: 0, freshness: 8.75 },
    ...(index === 8 ? {} : { skill_evidence: evidence }),
    work_matches: [
      {
        id: "api-development",
        label: catalog.work_tasks[0].label,
        required_skills: ["python", "http"],
        matched_skills: ["python"],
        missing_skills: ["http"],
        status: "partial",
      },
    ],
    // The renderer must ignore a hostile extra field even if a legacy snapshot has it.
    contact: "hidden-contact@example.invalid",
    about: "PRIVATE-FREE-TEXT",
  }));
  const requests: any[] = [];
  await page.route("**/api/v1/company/searches", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: "saved-current", rows }),
    });
  });
  await page.route("**/api/v1/company/searches/page?*", (route) => {
    const offset = Number(
      new URL(route.request().url()).searchParams.get("offset"),
    );
    const items = Array.from({ length: offset ? 1 : 8 }, (_, i) => ({
      id: `saved-${offset + i + 1}`,
      query: savedQuery,
    }));
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items, total: 9, offset, limit: 8 }),
    });
  });
  await page.route("**/api/v1/company/searches/saved-9", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ query: savedQuery, rows }),
    }),
  );
  await page.route("**/api/v1/company/searches/saved-1", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ query: baseQuery, rows }),
    }),
  );
  await page.goto("/#/employer/bank");
  const tasks = page.getByRole("group", {
    name: "Задачи команды",
    exact: true,
  });
  await tasks.getByRole("checkbox", { name: /Разработка API/ }).check();
  await expect(tasks).toContainText("Желательные навыки задач: python, http");
  await expect(
    page
      .getByRole("group", { name: "Обязательные навыки", exact: true })
      .getByLabel("http", { exact: true }),
  ).not.toBeChecked();
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page).toHaveURL(/work_tasks=api-development/);
  expect(requests.at(-1)).toMatchObject(savedQuery);
  const candidates = page.locator(".candidate-row");
  await expect(candidates).toHaveCount(8);
  await candidates
    .first()
    .getByText("Источники навыков и задачи команды", { exact: true })
    .click();
  await expect(candidates.first().locator(".work-matches")).toContainText(
    "Частичное покрытие",
  );
  await expect(candidates.first().locator(".work-matches")).toContainText(
    "Не подтверждены: http",
  );
  await candidates
    .first()
    .getByRole("button", { name: "Сравнить", exact: true })
    .click();
  const pages = page.getByRole("navigation", {
    name: "Страницы: Результаты подбора",
  });
  await pages.getByRole("button", { name: /Следующая страница/ }).click();
  await candidates
    .first()
    .getByRole("button", { name: "Сравнить", exact: true })
    .click();
  const comparison = page.getByRole("region", {
    name: "Сравнение кандидатов",
    exact: true,
  });
  await expect(comparison.locator(".comparison-profile")).toHaveCount(2);
  await expect(comparison).toContainText("источники навыков не сохранены");
  await expect(comparison).toContainText("scenarios-v5");
  await expect(page.locator("body")).not.toContainText(
    "hidden-contact@example.invalid",
  );
  await expect(page.locator("body")).not.toContainText("PRIVATE-FREE-TEXT");
  await noOverflow(page);
  const history = page.getByRole("navigation", {
    name: "Страницы: История подборок",
  });
  await history.getByRole("button", { name: /Следующая страница/ }).click();
  await tasks.getByRole("checkbox", { name: /Разработка API/ }).uncheck();
  await page
    .getByRole("combobox", { name: "Сохранённые подборки", exact: true })
    .selectOption("saved-9");
  await expect(
    tasks.getByRole("checkbox", { name: /Разработка API/ }),
  ).toBeChecked();
  await expect(pages.getByRole("status")).toContainText("страница 1 из 2");
  await expect(comparison).toHaveCount(0);
  await page.reload();
  await expect(
    tasks.getByRole("checkbox", { name: /Разработка API/ }),
  ).toBeChecked();
  await expect
    .poll(() => requests.at(-1)?.work_tasks)
    .toEqual(["api-development"]);
  await page
    .getByRole("combobox", { name: "Сохранённые подборки", exact: true })
    .selectOption("saved-1");
  await expect(
    tasks.getByRole("checkbox", { name: /Разработка API/ }),
  ).not.toBeChecked();
  expect(new URL(page.url()).searchParams.get("work_tasks")).toBe("");
  await page
    .getByLabel("Специализация", { exact: true })
    .selectOption("frontend");
  await expect(
    tasks.getByRole("checkbox", { name: /HTTP-клиент/ }),
  ).not.toBeChecked();
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.work_tasks).toEqual([]);
  expect(requests.at(-1).must_skills).toEqual(["javascript"]);
});

test("потребность переносит выбранные задачи в подборку, старая оценка сохраняет честные ограничения", async ({
  page,
}) => {
  await mockSession(page, "employer");
  let needs: any[] = [];
  let submitted: any;
  await page.route("**/api/v1/company/needs", async (route) => {
    if (route.request().method() === "POST") {
      submitted = route.request().postDataJSON();
      needs = [
        {
          id: "work-need",
          title: submitted.title,
          description: submitted.description,
          query: submitted,
        },
      ];
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(needs),
    });
  });
  await page.route("**/api/v1/company/searches", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        rows: [
          {
            id: "legacy-work",
            alias: "LEGACY-WORK",
            specialization: "backend",
            confirmed_grade: "junior",
            skills: ["python"],
            test_score: 75,
            salary_min: 100000,
            fsp_state: "none",
            fsp_evidence: [],
            skill_evidence: {
              declared: [],
              practice: [],
              limitations: ["Историческая детализация отсутствует."],
              assessment: [
                {
                  skill: "python",
                  score: null,
                  correct: null,
                  total: null,
                  version: null,
                  assessed_at: null,
                  source: "legacy-assessment",
                },
              ],
            },
          },
        ],
      }),
    }),
  );
  await page.goto("/#/employer/needs");
  await page
    .getByRole("group", { name: "Задачи команды", exact: true })
    .getByRole("checkbox", { name: /Разработка API/ })
    .check();
  await page
    .getByRole("button", { name: "Сохранить потребность", exact: true })
    .click();
  await expect(page.getByRole("status").first()).toContainText(
    "Потребность сохранена",
  );
  expect(submitted.work_tasks).toEqual(["api-development"]);
  expect(submitted.must_skills).toEqual(["python"]);
  await page
    .getByRole("button", { name: "Подобрать кандидатов", exact: true })
    .click();
  await expect(
    page
      .getByRole("group", { name: "Задачи команды", exact: true })
      .getByRole("checkbox", { name: /Разработка API/ }),
  ).toBeChecked();
  await page
    .locator(".candidate-row")
    .getByText("Источники навыков и задачи команды", { exact: true })
    .click();
  await expect(page.locator(".skill-evidence")).toContainText(
    "балл по навыку не сохранён",
  );
  await expect(page.locator(".skill-evidence")).toContainText(
    "версия не сохранена",
  );
  await expect(page.locator(".skill-evidence")).toContainText(
    "историческая оценка",
  );
  await expect(page.locator(".skill-evidence")).not.toContainText("0/100");
  await noOverflow(page);
});

test("новая сценарная форма сохраняет строки кода и таблиц на 320px и доступную пагинацию", async ({
  page,
}) => {
  await mockSession(page, "candidate");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const questions = [
    {
      id: "scenario-code",
      skill: "python",
      title:
        "values = [4, 4, 2]\nseen = set()\nfor value in values:\n    seen.add(value)\nprint(len(seen))\nКаким будет результат?",
      options: ["2", "3", "4"],
    },
    {
      id: "scenario-table",
      skill: "sql",
      title:
        'Таблица событий:\n[{"id":1,"owner":null},\n {"id":2,"owner":"demo"}]\nЧему равен COUNT(owner)?',
      options: ["1", "2", "0"],
    },
    {
      id: "scenario-http",
      skill: "http",
      title:
        "Сервис повторяет запрос с тем же ключом.\nКакой ответ следует вернуть?",
      options: ["Сохранённый ответ", "Всегда новый ответ"],
    },
  ];
  await page.route("**/api/v1/assessments/attempts/scenario-fixture", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "scenario-fixture",
        version: "scenarios-v5",
        grade: "junior",
        specialization: "backend",
        questions,
        answers: {},
        revision: 0,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        result: null,
      }),
    }),
  );
  await page.setViewportSize({ width: 320, height: 1000 });
  await page.goto("/#/candidate/assessment/scenario-fixture");
  await expect(
    page.getByText("Версия формы: scenarios-v5", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Независимой калибровки нет/)).toBeVisible();
  const legend = page.locator(".assessment-question legend");
  const code = page.locator(".assessment-question .code-sample");
  const split = (title: string) => {
    const lines = title.split("\n");
    return { prompt: lines[lines.length - 1], code: lines.slice(0, -1).join("\n") };
  };
  await expect(legend).toHaveText(`1. ${split(questions[0].title).prompt}`);
  await expect(code).toHaveText(split(questions[0].title).code);
  expect(
    await code.evaluate((element) => getComputedStyle(element).whiteSpace),
  ).toBe("pre-wrap");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(320);
  const pages = page.getByRole("navigation", {
    name: "Страницы: Вопросы оценки",
  });
  await pages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(legend).toHaveText(`2. ${split(questions[1].title).prompt}`);
  await expect(code).toContainText("Таблица событий:");
  await expect(
    page.getByRole("group", { name: /COUNT\(owner\)/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(320);
  await pages.getByRole("button", { name: /Следующая страница/ }).click();
  await expect(legend).toHaveText(`3. ${split(questions[2].title).prompt}`);
  await expect(
    pages.getByRole("button", { name: /Следующая страница/ }),
  ).toBeDisabled();
});
