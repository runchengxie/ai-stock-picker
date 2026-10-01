import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const research = defineCollection({
  loader: glob({
    base: './docs',
    pattern: ['research/*.md', 'zh-CN/research/*.md', '!research/README.md', '!zh-CN/research/README.md'],
    generateId: ({ entry }) => {
      const language = entry.startsWith('zh-CN/') ? 'zh-CN' : 'en';
      return `${language}/${entry.split('/').at(-1)?.replace(/\.md$/, '')}`;
    },
  }),
  schema: z.object({
    title: z.string().trim().min(1),
    summary: z.string().trim().min(1),
    date: z.coerce.date(),
    language: z.enum(['en', 'zh-CN']),
    slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  }),
});

export const collections = { research };
