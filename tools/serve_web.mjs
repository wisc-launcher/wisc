/** Local static preview with the same public release handler used by Vercel. */
import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import release from '../web/api/release.mjs';

const root = path.resolve(fileURLToPath(new URL('../dist/web/', import.meta.url)));
const port = Number(process.env.PORT || 3000);
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.xml': 'application/xml; charset=utf-8', '.txt': 'text/plain; charset=utf-8', '.png': 'image/png', '.ico': 'image/x-icon', '.ttf': 'font/ttf', '.woff2': 'font/woff2' };
// Preview the same redirects, page mappings, and 404 fallback as the website service.
const { routes } = JSON.parse(await readFile(new URL('../web/vercel.json', import.meta.url), 'utf8'));
const rules = routes.map(route => ({ ...route, pattern: route.src ? new RegExp(route.src) : undefined }));
async function staticFile(pathname) {
    const file = path.resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);
    if (!file.startsWith(`${root}${path.sep}`)) return undefined;
    try { return (await stat(file)).isFile() ? file : undefined; }
    catch { return undefined; }
}
http.createServer(async (req, res) => {
    try {
        const url = new URL(req.url, 'http://localhost');
        const pathname = decodeURIComponent(url.pathname);
        if (pathname !== '/api/release' && req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405, { Allow: 'GET, HEAD' }); return res.end(); }
        let file;
        let status = 200;
        const headers = {};
        for (const rule of rules) {
            if (rule.handle === 'filesystem') {
                if (pathname === '/api/release') {
                    for (const [key, value] of Object.entries(headers)) res.setHeader(key, value);
                    return await release(req, res);
                }
                file = await staticFile(pathname);
                if (file) break;
                continue;
            }
            if (!rule.pattern.test(pathname)) continue;
            const substitute = value => pathname.replace(rule.pattern, value);
            for (const [key, value] of Object.entries(rule.headers || {})) headers[key] = substitute(value);
            if (rule.continue) continue;
            status = rule.status || 200;
            if (headers.Location) {
                headers.Location += url.search;
                res.writeHead(status, headers);
                return res.end();
            }
            file = await staticFile(substitute(rule.dest || pathname));
            break;
        }
        if (!file) { file = path.join(root, '404.html'); status = 404; headers['X-Robots-Tag'] = 'noindex'; }
        const content = await readFile(file);
        res.writeHead(status, { ...headers, 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' });
        res.end(req.method === 'HEAD' ? undefined : content);
    } catch { res.writeHead(400); res.end('Bad request'); }
}).listen(port, '127.0.0.1', () => console.log(`Wisc preview: http://localhost:${port}`));
