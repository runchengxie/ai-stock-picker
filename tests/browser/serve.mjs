import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';

if (!process.env.AIPICK_SITE_OUTPUT) throw new Error('AIPICK_SITE_OUTPUT must point to the built site');
const root = resolve(process.env.AIPICK_SITE_OUTPUT);
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.svg': 'image/svg+xml' };
createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (!path.startsWith('/ai-stock-picker/')) throw new Error('Unknown route');
    let file = resolve(root, path.slice('/ai-stock-picker/'.length));
    if (file !== root && !file.startsWith(`${root}${sep}`)) throw new Error('Invalid path');
    if ((await stat(file)).isDirectory()) file = resolve(file, 'index.html');
    response.setHeader('Content-Type', types[extname(file)] ?? 'application/octet-stream');
    response.end(await readFile(file));
  } catch {
    response.writeHead(404).end('Not found');
  }
}).listen(8877, '127.0.0.1');
