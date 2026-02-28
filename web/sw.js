const CACHE_NAME = 'video-downloader-v1';
const DYNAMIC_CACHE = 'video-downloader-dynamic-v1';

// Assets to cache on install
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js',
  '/manifest.json',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/webfonts/fa-solid-900.woff2',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/webfonts/fa-brands-400.woff2'
];

// Install event - cache static assets
self.addEventListener('install', event => {
  console.log('[Service Worker] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[Service Worker] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
  console.log('[Service Worker] Activating...');
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME && key !== DYNAMIC_CACHE)
          .map(key => caches.delete(key))
      );
    }).then(() => {
      console.log('[Service Worker] Now ready to handle fetches');
      return self.clients.claim();
    })
  );
});

// Fetch event - cache with network fallback (stale-while-revalidate strategy)
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip cross-origin requests except CDNs
  if (url.origin !== location.origin && !url.hostname.includes('cdnjs')) {
    return;
  }

  // Handle API requests differently
  if (url.pathname.startsWith('/progress/') || 
      url.pathname.startsWith('/files') ||
      url.pathname.startsWith('/preview') ||
      url.pathname.startsWith('/start-download')) {
    // Network first for API requests
    event.respondWith(
      fetch(request)
        .then(response => {
          // Cache successful responses
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(DYNAMIC_CACHE).then(cache => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          // Fallback to cache if offline
          return caches.match(request);
        })
    );
    return;
  }

  // Stale-while-revalidate for static assets
  event.respondWith(
    caches.match(request).then(cachedResponse => {
      const fetchPromise = fetch(request)
        .then(networkResponse => {
          // Update cache with new response
          if (networkResponse.ok) {
            const responseClone = networkResponse.clone();
            caches.open(DYNAMIC_CACHE).then(cache => {
              cache.put(request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(error => {
          console.log('[Service Worker] Fetch failed:', error);
          return cachedResponse;
        });

      return cachedResponse || fetchPromise;
    })
  );
});

// Background sync for offline downloads
self.addEventListener('sync', event => {
  if (event.tag === 'sync-downloads') {
    event.waitUntil(syncDownloads());
  }
});

async function syncDownloads() {
  try {
    const db = await openDB();
    const pendingDownloads = await getPendingDownloads(db);
    
    for (const download of pendingDownloads) {
      try {
        await fetch('/start-download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(download)
        });
        await markDownloadComplete(db, download.id);
      } catch (error) {
        console.error('Failed to sync download:', error);
      }
    }
  } catch (error) {
    console.error('Background sync failed:', error);
  }
}

// Push notification handler
self.addEventListener('push', event => {
  const data = event.data.json();
  const options = {
    body: data.body,
    icon: '/icons/icon-192x192.png',
    badge: '/icons/icon-72x72.png',
    vibrate: [200, 100, 200],
    data: {
      url: data.url
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Notification click handler
self.addEventListener('notificationclick', event => {
  event.notification.close();
  
  if (event.notification.data.url) {
    event.waitUntil(
      clients.openWindow(event.notification.data.url)
    );
  }
});

// Helper functions for IndexedDB (simplified)
function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('VideoDownloaderDB', 1);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      db.createObjectStore('pendingDownloads', { keyPath: 'id' });
    };
  });
}

async function getPendingDownloads(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pendingDownloads', 'readonly');
    const store = tx.objectStore('pendingDownloads');
    const request = store.getAll();
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

async function markDownloadComplete(db, id) {
  const tx = db.transaction('pendingDownloads', 'readwrite');
  const store = tx.objectStore('pendingDownloads');
  store.delete(id);
}