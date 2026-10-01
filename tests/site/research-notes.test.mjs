import test from 'node:test';
import assert from 'node:assert/strict';
import { listResearchNotes } from '../../src/lib/research-notes.ts';

const note = (language, overrides = {}) => ({
  id: `${language}/stability`,
  data: {
    title: language === 'en' ? 'Stability' : '稳定性',
    summary: 'A short summary',
    date: new Date('2026-07-16'),
    language,
    slug: 'stability',
    ...overrides,
  },
});

test('returns a complete English and Chinese pair', () => {
  const notes = listResearchNotes([note('en'), note('zh-CN')]);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].slug, 'stability');
  assert.equal(notes[0].en.data.title, 'Stability');
  assert.equal(notes[0]['zh-CN'].data.title, '稳定性');
});

test('rejects a missing translation', () => {
  assert.throws(() => listResearchNotes([note('en')]), /exactly one.*en.*zh-CN/i);
});

test('rejects duplicate locale entries for one slug', () => {
  assert.throws(() => listResearchNotes([note('en'), note('en'), note('zh-CN')]), /duplicate/i);
});

test('rejects an unsupported language', () => {
  assert.throws(() => listResearchNotes([note('fr'), note('zh-CN')]), /language/i);
});

test('rejects missing required metadata', () => {
  assert.throws(() => listResearchNotes([note('en', { summary: '' }), note('zh-CN')]), /summary/i);
});
