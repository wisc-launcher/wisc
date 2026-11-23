'use strict';

const releaseStatus = document.querySelector('[data-release-status]');
if (releaseStatus) {
    fetch('/api/release', { signal: AbortSignal.timeout(10000) }).then(response => {
        if (!response.ok) throw new Error('Release unavailable');
        return response.json();
    }).then(release => {
        for (const button of document.querySelectorAll('[data-download]')) {
            const asset = release.assets[button.dataset.download];
            if (asset && /^https:\/\/github\.com\/wisc-launcher\/wisc\/releases\/download\//.test(asset.url)) {
                button.href = asset.url;
                if (button.dataset.download === 'installer') button.textContent = 'Download installer ↗';
                if (button.dataset.download === 'portable') button.textContent = 'Download portable ZIP ↗';
                if (button.dataset.download === 'checksums') button.textContent = 'Download checksums ↗';
            }
        }
        releaseStatus.textContent = `Latest published release: ${release.tag}. Files are hosted on GitHub.`;
    }).catch(() => {
        releaseStatus.textContent = 'Live release details are unavailable. Use the buttons to view the latest published files on GitHub.';
    });
}


const currentPath = location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/';
for (const link of document.querySelectorAll('nav .links a')) {
    if (link.getAttribute('href') === currentPath) link.setAttribute('aria-current', 'page');
}

// Ease vertical wheel input without changing touch, keyboard, or scrollbar control.
(() => {
    const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let destination = window.scrollY;
    let previousTime = 0;

    const limit = () => Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const clamp = value => Math.max(0, Math.min(value, limit()));

    function stop() {
        cancelAnimationFrame(frame);
        frame = 0;
        previousTime = 0;
        destination = window.scrollY;
    }

    function animate(time) {
        const elapsed = previousTime ? Math.min(time - previousTime, 50) : 16;
        previousTime = time;
        destination = clamp(destination);
        const remaining = destination - window.scrollY;
        if (Math.abs(remaining) < 0.75) {
            window.scrollTo({ top: destination, behavior: 'instant' });
            stop();
            return;
        }
        const progress = 1 - Math.exp(-elapsed / 85);
        const step = Math.sign(remaining) * Math.max(1, Math.abs(remaining) * progress);
        window.scrollTo({ top: window.scrollY + step, behavior: 'instant' });
        frame = requestAnimationFrame(animate);
    }

    function hasNativeScroller(event) {
        for (const element of event.composedPath()) {
            if (!(element instanceof Element) || element === document.body || element === document.documentElement) continue;
            if (element.matches('select, textarea, [contenteditable], [data-native-scroll]')) return true;
            const overflow = getComputedStyle(element).overflowY;
            if (!/^(auto|scroll|overlay)$/.test(overflow) || element.scrollHeight <= element.clientHeight) continue;
            if (event.deltaY < 0 && element.scrollTop > 0) return true;
            if (event.deltaY > 0 && element.scrollTop + element.clientHeight < element.scrollHeight - 1) return true;
        }
        return false;
    }

    window.addEventListener('wheel', event => {
        if (motionPreference.matches || event.defaultPrevented || !event.cancelable) return;
        if (event.ctrlKey || event.metaKey || event.shiftKey || !event.deltaY || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) {
            stop();
            return;
        }
        if (hasNativeScroller(event)) {
            stop();
            return;
        }
        if (!frame) destination = window.scrollY;
        const unit = event.deltaMode === 1 ? 20 : event.deltaMode === 2 ? window.innerHeight : 1;
        destination = clamp(destination + event.deltaY * unit);
        if (destination === window.scrollY) {
            stop();
            return;
        }
        event.preventDefault();
        if (!frame) frame = requestAnimationFrame(animate);
    }, { passive: false });

    window.addEventListener('pointerdown', stop, { passive: true });
    window.addEventListener('touchstart', stop, { passive: true });
    window.addEventListener('keydown', event => {
        if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) stop();
    });
    window.addEventListener('hashchange', stop);
    window.addEventListener('resize', stop);
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    motionPreference.addEventListener('change', stop);
})();
