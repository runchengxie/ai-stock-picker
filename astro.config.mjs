import { defineConfig } from "astro/config";
import { unified } from "@astrojs/markdown-remark";
import { fileURLToPath } from "node:url";
import researchLinks from "./site/research-links.mjs";

const base = "/ai-stock-picker";
const slugs = ["stability", "models", "guarded", "numeric", "turnover", "daily"];

export default defineConfig({
  site: "https://runchengxie.github.io",
  base,
  output: "static",
  markdown: {
    processor: unified({
      remarkPlugins: [[researchLinks, { base, docsRoot: fileURLToPath(new URL("./docs", import.meta.url)) }]],
    }),
  },
  redirects: Object.fromEntries(slugs.flatMap((slug) => [
    [`/research/zh-CN/research/${slug}.md`, `${base}/zh-CN/research/${slug}/`],
    [`/zh-CN/research/${slug}.md`, `${base}/research/${slug}/`],
  ])),
});
