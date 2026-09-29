// Minimal service worker for PWA installation and network pass-through.
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }
  event.respondWith(
    fetch(event.request).catch((error) => {
      return caches.match(event.request).then((cached) => {
        if (cached) {
          return cached;
        }
        throw error;
      });
    })
  );
});
