import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const output = process.env.AIPICK_SITE_OUTPUT ?? new URL('../../dist/', import.meta.url).pathname;
const file = (name) => resolve(output, name);
const required = [
  'index.html', 'tool.html',
  ...['stability', 'models', 'guarded', 'numeric', 'turnover', 'daily'].flatMap((slug) => [
    `research/${slug}/index.html`, `zh-CN/research/${slug}/index.html`,
  ]),
];

test('Astro build emits the homepage, tool page, and bilingual research notes', async () => {
  for (const route of required) {
    await readFile(file(route));
  }
});

test('homepage has a base-prefixed stylesheet and readable research fallback', async () => {
  const html = await readFile(file('index.html'), 'utf8');
  assert.match(html, /\/ai-stock-picker\/styles\.css/);
  assert.match(html, /Research results|研究结果|100/);
  assert.match(html, /research_only|research-only|research only/i);
  assert.match(html, /\/ai-stock-picker\/research\/stability\//);
  assert.doesNotMatch(html, /\/ai-stock-pickerresearch\//);
});

test('Chinese research notes have base-prefixed theme assets and the correct locale', async () => {
  const html = await readFile(file('zh-CN/research/stability/index.html'), 'utf8');
  assert.match(html, /lang="zh-CN"/);
  assert.match(html, /\/ai-stock-picker\/theme\.js/);
  assert.match(html, /data-paired-locale="en"/);
});
