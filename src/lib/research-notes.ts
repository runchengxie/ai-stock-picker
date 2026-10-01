import type { CollectionEntry } from 'astro:content';

export type ResearchNote = {
  slug: string;
  en: CollectionEntry<'research'>;
  'zh-CN': CollectionEntry<'research'>;
};

export function listResearchNotes(entries: CollectionEntry<'research'>[]): ResearchNote[] {
  const grouped = new Map<string, Partial<Record<'en' | 'zh-CN', CollectionEntry<'research'>>>>();
  for (const entry of entries) {
    const data = entry.data;
    if (data.language !== 'en' && data.language !== 'zh-CN') {
      throw new Error(`Unsupported research note language for ${entry.id}`);
    }
    if (!data.title?.trim()) throw new Error(`Research note ${entry.id} is missing title`);
    if (!data.summary?.trim()) throw new Error(`Research note ${entry.id} is missing summary`);
    if (!(data.date instanceof Date) || Number.isNaN(data.date.valueOf())) {
      throw new Error(`Research note ${entry.id} is missing a valid date`);
    }
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(data.slug)) {
      throw new Error(`Research note ${entry.id} has an invalid stable slug`);
    }
    const pair = grouped.get(data.slug) ?? {};
    if (pair[data.language]) throw new Error(`Duplicate ${data.language} research note for ${data.slug}`);
    pair[data.language] = entry;
    grouped.set(data.slug, pair);
  }

  return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([slug, pair]) => {
    if (!pair.en || !pair['zh-CN']) {
      throw new Error(`Research note ${slug} must have exactly one en and one zh-CN entry`);
    }
    return { slug, en: pair.en, 'zh-CN': pair['zh-CN'] };
  });
}
