import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  workers: 1,
  reporter: 'list',
  outputDir: process.env.AIPICK_BROWSER_OUTPUT ?? '/tmp/aipick-browser-results',
  use: { baseURL: 'http://127.0.0.1:8877/ai-stock-picker/', trace: 'retain-on-failure' },
  webServer: {
    command: 'node tests/browser/serve.mjs',
    url: 'http://127.0.0.1:8877/ai-stock-picker/',
  },
});
