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
  assert.match(html, /Offline rehearsal on 2026-07-18/);
  assert.match(html, /Source files and SHA-256 fingerprints/);
  assert.match(html, /[a-f0-9]{64}/);
});

test('Chinese research notes have base-prefixed theme assets and the correct locale', async () => {
  const html = await readFile(file('zh-CN/research/stability/index.html'), 'utf8');
  assert.match(html, /lang="zh-CN"/);
  assert.match(html, /\/ai-stock-picker\/theme\.js/);
  assert.match(html, /data-locale-en="\/ai-stock-picker\/research\/stability\/"/);
});

test('links in every rendered research note resolve to published pages or source documents', async () => {
  for (const route of required.filter((name) => name.includes('research/'))) {
    const html = await readFile(file(route), 'utf8');
    const page = new URL(route.replace(/index\.html$/, ''), 'https://runchengxie.github.io/ai-stock-picker/');
    for (const [, href] of html.matchAll(/<a\b[^>]*\bhref="([^"]+)"/g)) {
      const target = new URL(href, page);
      if (target.origin !== page.origin) continue;
      assert.ok(target.pathname.startsWith('/ai-stock-picker/'), `${route}: ${href}`);
      assert.ok(!target.pathname.endsWith('.md'), `${route}: unpublished Markdown link ${href}`);
      const relative = target.pathname.slice('/ai-stock-picker/'.length);
      await readFile(file(!relative || relative.endsWith('/') ? `${relative}index.html` : relative));
    }
  }
});

test('previously published broken language links redirect to the matching note', async () => {
  for (const slug of ['stability', 'models', 'guarded', 'numeric', 'turnover', 'daily']) {
    for (const [oldRoute, target] of [
      [`research/zh-CN/research/${slug}.md`, `zh-CN/research/${slug}/`],
      [`zh-CN/research/${slug}.md`, `research/${slug}/`],
    ]) {
      const html = await readFile(file(`${oldRoute}/index.html`), 'utf8');
      assert.ok(html.includes(`url=/ai-stock-picker/${target}`), oldRoute);
    }
  }
});
