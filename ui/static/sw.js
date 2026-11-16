// Mesora Blocks service worker: makes the app installable, loads assets fast, and shows an offline page.
// Live data (/api/...) always goes to the network and is never cached.
const VERSION = 'mesora-v2';
const SHELL = ['/static/app.css', '/static/app.js', '/static/icon.svg', '/static/offline.html'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;

  if (e.request.mode === 'navigate') {   // pages: always live; a friendly page when there's no network
    e.respondWith(fetch(e.request).catch(() => caches.match('/static/offline.html')));
    return;
  }
  if (url.pathname.startsWith('/static/')) {   // assets: always the latest from the network; the cache is for offline
    e.respondWith(caches.open(VERSION).then(c => fetch(e.request)
      .then(r => { if (r.ok) c.put(e.request, r.clone()); return r; })
      .catch(() => c.match(e.request))));
  }
});
