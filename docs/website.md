# Wisc Launcher website

The website lives in `web/`. Its homepage is adapted from the supplied Wisc
Launcher HTML, with the screenshots and icons bundled in `web/assets/images/`.
Supporting pages use the same layout, colors, and fonts. Edit the HTML files
and shared CSS/JavaScript directly; no frontend dependencies are required.

## Deploy from the repository root on Vercel

Import this Git repository and leave **Root Directory** at the repository root
(blank or `.`). Choose **Services** when Vercel presents its application preset.
The root `vercel.json` explicitly declares one `website` service:

- Service root: `web`.
- Service build command: `npm run build` from `web/`.
- Service output directory: `dist` (the repository's `web/dist/`).
- A top-level catch-all rewrite sends public requests to `website`.
- Service routes map clean page URLs to their HTML files and return the custom
  `404.html` document with HTTP 404 after static files and functions are checked.

This declaration deploys the website independently of the desktop Python
application and local work folders. `.vercelignore` filters uploads;
it does not prevent the GitHub import screen from finding application folders.
Build and function settings belong inside the website service in Services mode.
The service's `web/api/release.mjs` supplies current release metadata.

Push the updated root config and website package files before refreshing the
GitHub import screen. If the screen still lists Python applications, reload or
restart the import so it reads the latest commit. No Python installation or
desktop-launcher build is needed for the website deployment.

For a custom domain, set **SITE_URL** to its full origin, such as
`https://launcher.example.com`, and rebuild. Without it, the build uses
`VERCEL_PROJECT_PRODUCTION_URL`, then `VERCEL_URL`. These values populate
canonical URLs, social previews, the sitemap, robots rules, and `llms.txt`.
Local builds fall back to `http://localhost:3000`.
Each page has a descriptive search title, description, and social preview.
The build generates the sitemap and discovery page list from indexable HTML
pages, excluding error documents and redirect aliases. Set `SITE_URL` to the
public custom domain before deploying so search engines use that domain.

The secondary `web/vercel.json` uses the same website build when `web/` is
selected directly; keep the repository's shared `tools/build_web.mjs` available.
The normal deployment imports the repository root and reads its explicit
service declaration. Local root builds keep writing to `dist/web/` for preview.

## Local preview

Use Node.js 22 or newer. From the repository root:

```bash
npm run dev
```

Open `http://localhost:3000`. The preview supports clean page URLs, aliases,
the custom 404 page, and the public release API. `npm run build` creates the
static output; `npm run preview` serves an existing build. Change the preview
port with `PORT`, and set `SITE_URL` if canonical URLs should use that port.

Use `/docs`, `/download`, `/mods`, and the other extensionless page URLs.
Their `.html` and trailing-slash forms permanently redirect to the clean URL,
preserving query strings. Unknown addresses, including missing assets and API
paths, show the Wisc 404 page with HTTP 404; `/404` also returns HTTP 404.
The preview reads the same route rules as the Vercel website configuration.
When adding a page, include its name in the clean-page and redirect route
patterns in both Vercel configurations. The sitemap discovers it automatically
unless its robots metadata contains `noindex`.

## Downloads and public API

`GET /api/release` returns the latest stable GitHub release tag and any Windows
x64 installer, portable ZIP, and checksum assets. New packages use the Wisc name;
older releases can retain their original filenames. The fixed upstream is `wisc-launcher/wisc`; API clients
cannot supply an alternate upstream. Successful metadata is cached on Vercel.
Upstream failures return 503 and retain a GitHub release-page fallback in the
website. GET and HEAD are accepted; other methods return 405.

Installer buttons on the homepage open Downloads. Its links work without
JavaScript by going to the latest GitHub release. JavaScript replaces those
links with exact assets when live metadata is available.

## Guides, tools, and site files

The site includes all requested page categories: launcher, mods, modpacks,
skins, downloads, multiplayer, documentation, help, troubleshooting, about,
terms, privacy, cookies/storage, refunds, licenses, a page directory, performance guidance, and
403/404/429/500/502/503 error documents. Explicit service routes use `404.html`
for missing pages and static resources with HTTP 404. Each clean error-document
URL returns its matching HTTP status and is excluded from search indexing.
These routes do not replace Vercel's own platform error screens.

The `doctor.html` page provides a static launch checklist. `benchmarks.html`
provides Java, memory, and measurement guidance without presenting unverified
performance results. The requested sample `cubeon-bench` path redirects to
that performance guide. No benchmark application is added or advertised.
The guides reflect current repository behavior: offline usernames and Ely.by
accounts, Ely.by sign-in to unlock skin customization, Windows x64 packages,
and the existing mod and modpack installation flows.

`robots.txt`, `sitemap.xml`, `llms.txt`, `favicon.ico`, `_redirects`, and both
Vercel configurations are included. The `_redirects` file is for compatible
static hosts; Vercel uses its JSON redirects. `indexnow-key.txt` and the matching
key-named text file provide an IndexNow ownership key. Publishing these files
does not submit URLs automatically: once the domain is live, use the key in
an IndexNow submission with its public key-file URL.

Source HTML contains `__SITE_URL__` placeholders; deploy the generated output
for correct production metadata. Existing launcher font notices and the GPL
license are preserved in `web/assets/licenses/`. Minecraftia and Inter are bundled in
`web/assets/fonts/`. Their attribution, font notices, and Inter’s SIL Open Font
License are retained in `web/assets/licenses/`. The site makes no Google Fonts requests.

Local validation scripts and screenshots belong in ignored `temp/`. They are
not included in a clone or required for deployment.
With the local scripts and their Python dependencies present, start the preview
and run `python -B -m unittest temp.test_web_routes_seo temp.test_web_routes_browser`
from the repository root. These local-only checks cover clean routes, redirects,
HTTP error statuses, metadata, sitemap entries, and the desktop/mobile 404 layout.
