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

function _resolveTargetUrl(rawUrl) {
  const scope = (self.registration && self.registration.scope) || (self.location && self.location.origin + '/') || '/';
  if (!rawUrl || rawUrl === '/') {
    return scope;
  }
  if (/^https?:\/\//i.test(rawUrl)) {
    return rawUrl;
  }
  const scopeUrl = new URL(scope, self.location ? self.location.origin : undefined);
  const scopePath = scopeUrl.pathname.replace(/\/+$/, '');
  if (!rawUrl.startsWith('/')) {
    return new URL(rawUrl, scopeUrl.href).href;
  }
  if (scopePath && !rawUrl.startsWith(scopePath + '/') && rawUrl !== scopePath) {
    const combined = scopePath + rawUrl;
    return new URL(combined, scopeUrl.origin).href;
  }
  return new URL(rawUrl, scopeUrl.origin).href;
}

self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { body: event.data.text() };
    }
  }
  const defaultIcon = _resolveTargetUrl('favicon.ico');
  const title = data.title || 'Private Engine';
  const options = {
    body: data.body || '',
    icon: data.icon || defaultIcon,
    badge: data.badge || defaultIcon,
    data: { url: data.url || './' },
    tag: data.tag || 'default'
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const rawUrl = (event.notification.data && event.notification.data.url) || './';
  const targetUrl = _resolveTargetUrl(rawUrl);
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url === targetUrl || (targetUrl.includes('?s=') && client.url.includes(targetUrl.split('?')[1]))) {
          if ('focus' in client) {
            return client.focus();
          }
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
