/** Public, cached release metadata; the repository and upstream are fixed. */
const repository = 'wisc-launcher/wisc';
const releasePage = `https://github.com/${repository}/releases/latest`;

function respond(res, status, payload, head = false) {
    res.statusCode = status;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.end(head ? undefined : JSON.stringify(payload));
}

export default async function handler(req, res) {
    const head = req.method === 'HEAD';
    if (req.method !== 'GET' && !head) {
        res.setHeader('Allow', 'GET, HEAD');
        res.setHeader('Cache-Control', 'no-store');
        return respond(res, 405, { error: 'Method not allowed' });
    }
    try {
        const response = await fetch(`https://api.github.com/repos/${repository}/releases/latest`, {
            headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Wisc-Launcher-Website', 'X-GitHub-Api-Version': '2022-11-28' },
            signal: AbortSignal.timeout(8000),
            redirect: 'error',
        });
        if (!response.ok) throw new Error('Release metadata unavailable');
        const release = await response.json();
        if (typeof release.tag_name !== 'string' || release.draft || release.prerelease || !Array.isArray(release.assets)) throw new Error('Invalid release');
        const assets = { installer: null, portable: null, checksums: null };
        for (const asset of release.assets) {
            if (typeof asset.name !== 'string' || typeof asset.browser_download_url !== 'string') continue;
            const url = new URL(asset.browser_download_url);
            if (url.protocol !== 'https:' || url.host !== 'github.com' || url.username || url.password || !url.pathname.startsWith(`/${repository}/releases/download/`)) continue;
            const kind = /windows-x64-setup\.exe$/i.test(asset.name) ? 'installer' : /windows-x64\.zip$/i.test(asset.name) ? 'portable' : asset.name === 'SHA256SUMS.txt' ? 'checksums' : null;
            if (kind && !assets[kind]) assets[kind] = { name: asset.name, url: url.href, size: Number.isFinite(asset.size) ? asset.size : null };
        }
        res.setHeader('Cache-Control', 'public, max-age=60, s-maxage=300, stale-while-revalidate=600');
        return respond(res, 200, { tag: release.tag_name, name: typeof release.name === 'string' ? release.name : release.tag_name, publishedAt: release.published_at ?? null, url: releasePage, assets }, head);
    } catch {
        res.setHeader('Cache-Control', 'no-store');
        return respond(res, 503, { error: 'Live release details are temporarily unavailable.', url: releasePage }, head);
    }
}
