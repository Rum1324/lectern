// Lectern service worker: lets Android Chrome install the page as an app. Only the app shell
// is cached, as a fallback; /ws and everything else go straight to the network.
const CACHE = "lectern-v3";
const SHELL = ["/", "/icon.png", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const old = (await caches.keys()).filter((k) => k !== CACHE);
    await Promise.all(old.map((k) => caches.delete(k)));
    await self.clients.claim();
    // Replacing an older worker: reload the open app, which that worker may have served from
    // its cache, so an update shows on this launch rather than the next one.
    if (old.length) for (const c of await self.clients.matchAll({ type: "window" })) c.navigate(c.url).catch(() => {});
  })());
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname === "/ws") return;
  const key = url.pathname === "/index.html" ? "/" : url.pathname;
  if (!SHELL.includes(key)) return;
  // Shell: network first, so every launch gets the page the Mac serves now. The cached copy is
  // for when the Mac can't be reached (the page then shows Reconnecting…).
  e.respondWith(caches.open(CACHE).then((c) => fetch(e.request)
    .then((r) => { if (r.ok) { c.put(key, r.clone()); return r; } return c.match(key).then((m) => m || r); })
    .catch(() => c.match(key))));
});
