import { dirname, relative, resolve, sep } from 'node:path';

// Keep Markdown source links usable on GitHub; resolve them for the website at build time.
export default function researchLinks({ base, docsRoot }) {
  return (tree, file) => {
    const rewrite = (node) => {
      if (node.type === 'link' || node.type === 'definition') {
        const match = node.url?.match(/^([^?#]+\.md)([?#].*)?$/);
        if (match && !/^(?:[a-z]+:|\/)/i.test(match[1])) {
          const document = relative(docsRoot, resolve(dirname(file.path), match[1])).split(sep).join('/');
          const note = document.match(/^(zh-CN\/)?research\/([a-z0-9-]+)\.md$/);
          if (note && note[2] !== 'README') {
            node.url = `${base}/${note[1] ?? ''}research/${note[2]}/${match[2] ?? ''}`;
          } else if (!document.startsWith('../')) {
            node.url = `https://github.com/runchengxie/ai-stock-picker/blob/main/docs/${document}${match[2] ?? ''}`;
          }
        }
      }
      for (const child of node.children ?? []) rewrite(child);
    };
    rewrite(tree);
  };
}
