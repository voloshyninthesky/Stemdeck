const CACHE_PREFIX = "stemdeck-";
const CACHE_NAME = "stemdeck-v24";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", () => {
  // Network-only on purpose. Old cached app shells caused stale JS to keep controls inert.
});
