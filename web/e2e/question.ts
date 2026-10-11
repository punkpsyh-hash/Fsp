import type { Page } from "@playwright/test";

// Текст задания целиком: код или данные показаны блоком, последняя строка формы — вопрос в legend.
export async function questionTitle(page: Page): Promise<string> {
  const prompt = (await page.locator("fieldset legend").innerText()).replace(/^\d+\.\s*/, "");
  const code = page.locator(".assessment-question .code-sample");
  if (!(await code.count())) return prompt;
  return `${(await code.first().innerText()).replace(/\n+$/, "")}\n${prompt}`;
}
