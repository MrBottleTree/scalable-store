"use strict";
const SW_VERSION = '1.0.5';
const CACHE_NAME = 'pwa-cache-v15';

const urlsToCache = [
  '/',
  '/offline/',
  'https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
];

function logToPage(message) {
  self.clients.matchAll().then(function(clients) {
    clients.forEach(function(client) {
      client.postMessage(message);
    });
  });
}

self.addEventListener('install', event => {
  self.skipWaiting();
  logToPage('Service Worker: Install event');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        logToPage('Service Worker: Cache opened ' + CACHE_NAME);
        return Promise.allSettled(
          urlsToCache.map(url => {
            return cache.add(url).catch(error => {
              logToPage('Failed to cache ' + url);
            });
          })
        );
      })
  );
});

self.addEventListener('activate', event => {
  logToPage('Service Worker: Activate event');
  event.waitUntil(
    Promise.all([
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames
            .filter(cacheName => cacheName.startsWith('pwa-cache-'))
            .filter(cacheName => cacheName !== CACHE_NAME)
            .map(cacheName => {
              logToPage('Service Worker: Deleting old cache ' + cacheName);
              return caches.delete(cacheName);
            })
        );
      }),
      self.clients.claim()
    ])
  );
});

self.addEventListener('fetch', event => {
  const requestUrl = event.request.url;

  if (requestUrl.includes('manifest.json')) {
    logToPage('Service Worker: Fetching fresh manifest: ' + requestUrl);
    event.respondWith(fetch(event.request));
    return;
  }

  if (!requestUrl.startsWith(self.location.origin) &&
      !requestUrl.includes('googleapis.com') &&
      !requestUrl.includes('cdnjs.cloudflare.com')) {
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/offline/'))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(event.request).then(response => {
        if (!response || response.status !== 200 || response.type !== 'basic') {
          return response;
        }

        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, responseToCache);
        });

        return response;
      }).catch(error => {
        logToPage('Service Worker: Fetch failed: ' + error);

        if (requestUrl.match(/\.(jpg|jpeg|png|gif|svg)$/)) {
          return caches.match('/static/images/placeholder.png');
        }
      });
    })
  );
});

self.addEventListener('push', function(event) {
  logToPage('Push event received.');

  if (event.data) {
    const data = event.data.json();
    logToPage('Push payload: ' + JSON.stringify(data));

    const title = data.title || "BITS Pilani Pawnshop";
    const options = {
      body: data.body || "New update available!",
      icon: '/static/images/icon_192.png',
      badge: '/static/images/icon_144.png',
      data: {
        url: data.url || '/'
      }
    };

    if (data.image) {
      options.image = data.image;
      logToPage('Image added to push: ' + data.image);
    }

    event.waitUntil(
      self.registration.showNotification(title, options)
    );
  } else {
    logToPage('Push event received but no data was sent.');
  }
});


self.addEventListener('notificationclick', function(event) {
  logToPage('Notification click received.');
  event.notification.close();

  event.waitUntil(
    clients.matchAll({ type: "window" }).then(function(clientList) {
      for (const client of clientList) {
        if (client.url === '/' && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow('/');
      }
    })
  );
});
