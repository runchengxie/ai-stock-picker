import { test, expect } from '@playwright/test';

test('homepage switches the header, results, and note links and remembers the language', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('./');
  const picker = page.locator('#language');
  await expect(picker).toBeEnabled();
  await picker.selectOption('zh-CN');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await expect(page.locator('[data-i18n="research.nav.results"]')).toHaveText('研究结果');
  await expect(page.locator('#research-app')).toBeVisible();
  await expect(page.locator('[data-note-slug="daily"]')).toHaveAttribute('href', /\/zh-CN\/research\/daily\/$/);
  await page.reload();
  await expect(picker).toHaveValue('zh-CN');
  await picker.selectOption('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(errors).toEqual([]);
});

for (const slug of ['daily', 'stability', 'models', 'guarded', 'numeric', 'turnover']) {
  test(`${slug}: the top selector matches the current note and switches both ways`, async ({ page }) => {
    await page.goto(`zh-CN/research/${slug}/`);
    const picker = page.locator('#language');
    await expect(picker).toHaveValue('zh-CN');
    await expect(page.locator('main a').filter({ hasText: /^(English|简体中文)$/ })).toHaveCount(0);
    await picker.selectOption('en');
    await expect(page).toHaveURL(new RegExp(`/ai-stock-picker/research/${slug}/$`));
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(picker).toHaveValue('en');
    await picker.selectOption('zh-CN');
    await expect(page).toHaveURL(new RegExp(`/ai-stock-picker/zh-CN/research/${slug}/$`));
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await page.locator('.brand').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  });
}

test('language switching remains usable when browser storage is blocked', async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = Storage.prototype.setItem = () => { throw new DOMException('Blocked', 'SecurityError'); };
  });
  await page.goto('./');
  await expect(page.locator('#language')).toBeEnabled();
  await page.locator('#language').selectOption('zh-CN');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await page.locator('[data-note-slug="daily"]').click();
  await expect(page.locator('#language')).toHaveValue('zh-CN');
  await page.locator('#language').selectOption('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

test('tool page uses the same saved language and switches through its top selector', async ({ page }) => {
  await page.goto('./');
  await expect(page.locator('#language')).toBeEnabled();
  await page.locator('#language').selectOption('zh-CN');
  await page.goto('tool.html');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await expect(page.locator('#language')).toHaveValue('zh-CN');
  await page.locator('#language').selectOption('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

test('missing Chinese catalog falls back to an operable English page', async ({ page }) => {
  await page.route('**/locales/zh-CN.json', (route) => route.fulfill({ status: 404, body: 'Not found' }));
  await page.goto('./');
  await expect(page.locator('#language')).toBeEnabled();
  await page.locator('#language').selectOption('zh-CN');
  await expect(page.locator('#language')).toHaveValue('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});
