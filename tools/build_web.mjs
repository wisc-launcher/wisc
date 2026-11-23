/** Dependency-free static build; all source pages and artwork live in web/. */
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'web');
if (process.argv.slice(2).some(argument => argument !== '--service')) throw new Error('Usage: node tools/build_web.mjs [--service]');
const output = process.argv.includes('--service') ? path.join(source, 'dist') : path.join(root, 'dist', 'web');
const configured = process.env.SITE_URL || process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL || 'http://localhost:3000';
const site = new URL(configured.includes('://') ? configured : `https://${configured}`);
if (!['http:', 'https:'].includes(site.protocol) || site.username || site.password || site.pathname !== '/' || site.search || site.hash) throw new Error('SITE_URL must be a plain HTTP(S) origin, for example https://launcher.example.com');
const origin = site.origin;
const decodeHtml = value => value.replace(/&(amp|quot|lt|gt|#x27);/g, entity => ({ '&amp;': '&', '&quot;': '"', '&lt;': '<', '&gt;': '>', '&#x27;': "'" })[entity]);
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const item of await readdir(source, { withFileTypes: true })) {
    if (['api', 'vercel.json', 'dist', 'node_modules', 'package.json', 'package-lock.json', '.vercel'].includes(item.name)) continue;
    await cp(path.join(source, item.name), path.join(output, item.name), { recursive: true });
}
let pages = 0;
const indexable = [];
async function finish(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
        const file = path.join(directory, entry.name);
        if (entry.isDirectory()) await finish(file);
        else if (/\.(html|xml|txt)$/.test(entry.name)) {
            let content = (await readFile(file, 'utf8')).replaceAll('__SITE_URL__', origin);
            if (entry.name.endsWith('.html')) {
                pages++;
                if (directory === output) {
                    const robots = content.match(/<meta\b(?=[^>]*\bname=["']robots["'])[^>]*>/i)?.[0] || '';
                    if (!/\bnoindex\b/i.test(robots)) {
                        const pathname = entry.name === 'index.html' ? '/' : `/${entry.name.slice(0, -5)}`;
                        const title = content.match(/<title>(.*?)<\/title>/i)?.[1];
                        const descriptionTag = content.match(/<meta\b(?=[^>]*\bname="description")[^>]*>/i)?.[0];
                        const description = descriptionTag?.match(/\bcontent="([^"]*)"/i)?.[1];
                        if (!title || !description) throw new Error(`Missing SEO metadata in ${entry.name}`);
                        indexable.push({ pathname, title: decodeHtml(title), description: decodeHtml(description) });
                    }
                }
                if (entry.name === 'index.html' && directory === output) {
                    const structuredData = { '@context': 'https://schema.org', '@type': 'SoftwareApplication', name: 'Wisc Launcher', applicationCategory: 'GameApplication', operatingSystem: 'Windows; Linux; macOS', url: `${origin}/`, downloadUrl: `${origin}/download`, license: 'https://www.gnu.org/licenses/gpl-3.0.html', offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' } };
                    const website = { '@context': 'https://schema.org', '@type': 'WebSite', name: 'Wisc Launcher', url: `${origin}/`, inLanguage: 'en' };
                    content = content.replace('</head>', [structuredData, website].map(data => `<script type="application/ld+json">${JSON.stringify(data).replaceAll('<', '\\u003c')}</script>`).join('') + '</head>');
                }
            }
            await writeFile(file, content);
        }
    }
}
await finish(output);
indexable.sort((a, b) => a.pathname.localeCompare(b.pathname));
const escapeXml = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&apos;');
await writeFile(path.join(output, 'sitemap.xml'), '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + indexable.map(page => `  <url><loc>${escapeXml(origin + page.pathname)}</loc></url>`).join('\n') + '\n</urlset>\n');
// Keep the discovery file in sync with the actual indexable pages and their metadata.
const discoveryFile = path.join(output, 'llms.txt');
const discovery = await readFile(discoveryFile, 'utf8');
await writeFile(discoveryFile, discovery.replace(/## Website\n[\s\S]*?(?=\n## Current project details)/, '## Website\n\n' + indexable.map(page => `- [${page.title}](${origin}${page.pathname}): ${page.description}`).join('\n') + '\n'));
console.log(`Built ${pages} Wisc pages in ${path.relative(root, output)} for ${origin}`);
