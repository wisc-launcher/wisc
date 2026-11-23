'use strict';

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const reveals = document.querySelectorAll('.rv');
const revealObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
        if (entry.isIntersecting) {
            entry.target.classList.add('in');
            revealObserver.unobserve(entry.target);
        }
    }
}, { threshold: 0.1 });
reveals.forEach(element => revealObserver.observe(element));

const screens = ['/assets/images/home.png', '/assets/images/library.png', '/assets/images/skins.png'];
const captions = [
    ['Play from Home', 'Jump into your last profile, see your skin, and launch with one big button.'],
    ['Profiles, organized', 'Create instances, reorder them by drag, and open mods, folders or settings from each row.'],
    ['Your skins, kept local', 'Import a PNG, preview it in 3D, and switch between everything you have saved.'],
];
const center = document.getElementById('rc');
const left = document.getElementById('rl');
const right = document.getElementById('rr');
const title = document.getElementById('ct');
const caption = document.getElementById('cp');
const previewElements = [center, left, right, title, caption];
let pendingPreview;
for (const button of document.querySelectorAll('.tab')) {
    button.addEventListener('click', () => {
        clearTimeout(pendingPreview);
        document.querySelectorAll('.tab').forEach(tab => {
            tab.classList.toggle('on', tab === button);
            tab.setAttribute('aria-pressed', String(tab === button));
        });
        const index = Number(button.dataset.i);
        const update = () => {
            center.src = screens[index];
            center.alt = `${captions[index][0]} launcher preview`;
            left.src = screens[(index + 2) % 3];
            right.src = screens[(index + 1) % 3];
            title.textContent = captions[index][0];
            caption.textContent = captions[index][1];
            previewElements.forEach(element => { element.style.opacity = ''; });
        };
        if (reducedMotion) update();
        else {
            previewElements.forEach(element => { element.style.opacity = '0'; });
            pendingPreview = setTimeout(update, 180);
        }
    });
}

fetch('/assets/images/showcase.json').then(response => {
    if (!response.ok) throw new Error('Showcase unavailable');
    return response.json();
}).then(({ mods }) => {
    const marquee = document.getElementById('mq');
    for (let index = 0; index < 2; index++) {
        const track = document.createElement('div');
        track.className = `track${index ? ' r' : ''}`;
        const names = Object.keys(mods);
        if (index) names.reverse();
        for (let repeat = 0; repeat < 4; repeat++) {
            for (const name of names) {
                const tile = document.createElement('div');
                tile.className = 'tile';
                if (repeat) tile.setAttribute('aria-hidden', 'true');
                const icon = document.createElement('img');
                icon.className = 'ico';
                icon.src = mods[name];
                icon.alt = '';
                icon.width = icon.height = 36;
                tile.append(icon, document.createTextNode(name));
                track.append(tile);
            }
        }
        marquee.append(track);
    }
}).catch(() => { document.getElementById('mq').hidden = true; });

const hero = document.querySelector('.hero');
const canvas = document.getElementById('bg');
const context = canvas.getContext('2d');
const tilt = document.getElementById('tilt');

function drawBackground() {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    const width = hero.clientWidth;
    const height = hero.clientHeight;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.lineWidth = 1;
    for (let line = 0; line < 30; line++) {
        const baseline = 40 + line * height * 0.82 / 30;
        context.beginPath();
        context.strokeStyle = `rgba(255,255,255,${0.05 + 0.07 * (0.5 + 0.5 * Math.sin(line * 0.5))})`;
        for (let x = 0; x <= width; x += 8) {
            const y = baseline + 26 * Math.sin(x * 0.004 + line * 0.22) + 14 * Math.sin(x * 0.009 + line * 0.4);
            if (x) context.lineTo(x, y); else context.moveTo(x, y);
        }
        context.stroke();
    }
}

let tiltFrame = 0;
function updateTilt() {
    tiltFrame = 0;
    if (reducedMotion) {
        tilt.style.transform = 'none';
        return;
    }
    const progress = Math.min(window.scrollY / 460, 1);
    tilt.style.transform = `rotateX(${18 * (1 - progress)}deg) scale(${0.94 + 0.06 * progress})`;
}
window.addEventListener('scroll', () => {
    if (!tiltFrame) tiltFrame = requestAnimationFrame(updateTilt);
}, { passive: true });
new ResizeObserver(drawBackground).observe(hero);
document.fonts.ready.then(drawBackground);
updateTilt();
