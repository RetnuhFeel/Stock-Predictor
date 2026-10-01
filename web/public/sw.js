/* Service worker: installability + offline app shell.

   - Only same-origin GET requests are handled. API calls (cross-origin) are never touched, so API errors
     can't be cached. The last-known *data* is kept by the page in localStorage ("last good" copies).
   - Navigations are network-first (fresh deploys win) and fall back to the cached page, then /offline.html.
   - Hashed /_next/static/ assets are cache-first (their URL changes whenever the content does).
   - Only successful (200, same-origin) responses are ever stored. Old caches are deleted on activate.
   - The page tells us which assets it loaded (message below) so the very first visit is fully available offline,
     even though those requests happened before this worker controlled the page. */
const VERSION = "v6";
const SHELL = `shell-${VERSION}`;
const ASSETS = `assets-${VERSION}`;
const OFFLINE_URL = "/offline.html";
const PRECACHE = [OFFLINE_URL, "/", "/terms", "/privacy", "/model", "/track-record", "/icon-192.png"];

const cacheable = (res) => res && res.ok && res.status === 200 && res.type === "basic";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => Promise.allSettled(PRECACHE.map((u) => c.add(new Request(u, { cache: "reload" }))))),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== ASSETS).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type !== "CACHE_URLS" || !Array.isArray(event.data.urls)) return;
  const urls = event.data.urls
    .map((u) => { try { return new URL(u, self.location.origin); } catch { return null; } })
    .filter((u) => u && u.origin === self.location.origin && u.pathname.startsWith("/_next/static/"))
    .slice(0, 100);
  event.waitUntil(
    caches.open(ASSETS).then((c) => Promise.allSettled(urls.map(async (u) => {
      if (await c.match(u.href)) return;
      const res = await fetch(u.href);
      if (cacheable(res)) await c.put(u.href, res);
    }))),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (cacheable(res)) {
          const c = await caches.open(SHELL);
          await c.put(req, res.clone());
        }
        return res;
      } catch {
        return (await caches.match(req, { ignoreSearch: true })) || (await caches.match("/")) || (await caches.match(OFFLINE_URL));
      }
    })());
    return;
  }

  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icon") || url.pathname === "/manifest.webmanifest") {
    event.respondWith((async () => {
      const hit = await caches.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (cacheable(res)) {
        const c = await caches.open(ASSETS);
        await c.put(req, res.clone());
      }
      return res;
    })());
  }
});
