const CACHE = 'axiom-driver-v2';
const CORE = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(CORE)).then(() => self.skipWaiting())
));

self.addEventListener('activate', event => event.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())
));

async function cacheSuccessful(request, response) {
  if (response && response.ok && response.type === 'basic') {
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => undefined);
  }
  return response;
}

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  // Never replay stale operational API data from the shell cache. The app's
  // durable queue owns offline mutations and explicitly handles API failures.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).then(response => cacheSuccessful(event.request, response)).catch(() => caches.match('./index.html')));
    return;
  }

  // Stale-while-revalidate keeps the shell instant while allowing deployments
  // to refresh cached assets without waiting for the next visit.
  event.respondWith(caches.match(event.request).then(cached => {
    const network = fetch(event.request).then(response => cacheSuccessful(event.request, response));
    return cached || network.catch(() => caches.match('./index.html'));
  }));
});
