// Lectern service worker: lets Android Chrome install the page as an app and open it
// instantly. Only the app shell is cached; /ws and everything else go straight to the network.
const CACHE = "lectern-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icon.png", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname === "/ws") return;
  const key = url.pathname === "/index.html" ? "/" : url.pathname;
  if (!SHELL.includes(key)) return;
  // Shell: serve from cache, refresh the copy in the background (stale-while-revalidate).
  e.respondWith(caches.open(CACHE).then(async (c) => {
    const cached = await c.match(key);
    const fresh = fetch(e.request).then((r) => { if (r.ok) c.put(key, r.clone()); return r; }).catch(() => cached);
    return cached || fresh;
  }));
});
