/* Реальные снимки синтетического стенда; запуск в проектном Playwright-контейнере. */
const { chromium } = require('/app/web/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const out = process.env.FSP_SCREEN_OUT || '/evidence';
  const url = process.env.FSP_SCREEN_URL || 'http://127.0.0.1:8470/';
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const errors = [];
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  const shots = [];
  async function shot(id, caption) {
    await page.waitForLoadState('networkidle');
    if (id === 'employer-search') await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.innerText.trim() === 'Найти' && !button.disabled));
    await page.waitForFunction(() => !document.body.innerText.includes('Загрузка'));
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: path.join(out, id + '.png'), fullPage: false});
    shots.push({id, caption, viewport: {width: 1440, height: 1000}, source: 'Работающий синтетический стенд NAS, Chromium; 11 октября 2026 года'});
  }
  await page.goto(url, {waitUntil: 'networkidle'});
  await shot('landing', 'Начальная страница и выбор демонстрационного кабинета');
  const demoLabels = await page.getByRole('button').allTextContents();
  await page.getByRole('button', {name: /Демо-команда X/}).click();
  await page.getByRole('navigation', {name: 'Разделы кабинета'}).waitFor();
  await shot('employer-search', 'Банк кандидатов в кабинете работодателя');
  await page.getByRole('button', {name: 'Конструктор заданий', exact: true}).click();
  await page.getByLabel('Название нового набора').waitFor();
  await shot('question-bank', 'Конструктор и версии практических наборов');
  const constructors = page.getByRole('button', {name: 'Открыть конструктор', exact: true});
  if (await constructors.count()) await constructors.first().click();
  const versions = page.getByLabel('Открыть версию');
  if (await versions.count()) {
    const value = await versions.first().locator('option').last().getAttribute('value');
    if (value) await versions.first().selectOption(value);
    const ai = page.getByText('Черновик с ИИ', {exact: true});
    if (await ai.count()) {
      await ai.scrollIntoViewIfNeeded();
      await shot('ai-draft', 'Форма создания черновика задания с помощью подключённой модели');
    }
  }
  await context.close();
  const candidateContext = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
  const candidate = await candidateContext.newPage();
  candidate.on('pageerror', error => errors.push(error.message));
  await candidate.goto(url, {waitUntil: 'networkidle'});
  const labels = await candidate.getByRole('button').allTextContents();
  const label = labels.find(x => /Кандидат/.test(x) && !/Создать|Стать/.test(x));
  if (!label) throw new Error('Не найден демонстрационный кандидат: ' + JSON.stringify(demoLabels));
  await candidate.getByRole('button', {name: /Кандидат А/}).first().click();
  await candidate.getByRole('navigation', {name: 'Разделы кабинета'}).waitFor();
  async function candidateShot(id, caption, tab) {
    if (tab) await candidate.getByRole('button', {name: tab, exact: true}).click();
    if (id === 'candidate-profile') await candidate.getByRole('button', {name: 'Сохранить профиль', exact: true}).waitFor();
    if (id === 'privacy') await candidate.getByRole('heading', {name: 'Получатели контакта', exact: true}).waitFor();
    if (tab === 'Практические наборы') await candidate.getByRole('heading', {name: tab, exact: true, level: 2}).waitFor();
    await candidate.waitForLoadState('networkidle');
    await candidate.waitForFunction(() => !document.body.innerText.includes('Загрузка'));
    await candidate.evaluate(() => window.scrollTo(0, 0));
    await candidate.screenshot({path: path.join(out, id + '.png'), fullPage: false});
    shots.push({id, caption, viewport: {width: 1440, height: 1000}, source: 'Работающий синтетический стенд NAS, Chromium; 11 октября 2026 года'});
  }
  await candidateShot('candidate-profile', 'Профиль кандидата и источники сведений о навыках');
  await candidateShot('privacy', 'Настройки доступности профиля и контактов', 'Приватность');
  await candidateShot('practice', 'Практические наборы в кабинете кандидата', 'Практические наборы');
  await candidateContext.close();
  await browser.close();
  if (errors.length) throw new Error(JSON.stringify(errors));
  fs.writeFileSync(path.join(out, 'capture.json'), JSON.stringify({captured_at: new Date().toISOString(), screenshots: shots, page_errors: errors}, null, 2));
  console.log(JSON.stringify({screenshots: shots.length, page_errors: 0}));
})().catch(error => { console.error(error.message); process.exit(1); });
