/* Service worker: installability + offline app shell.

   - Only same-origin GET requests are handled. API calls (cross-origin) are never touched, so API errors
     can't be cached. The last-known *data* is kept by the page in localStorage ("last good" copies).
   - Navigations are network-first (fresh deploys win) and fall back to the cached page, then /offline.html.
   - Hashed /_next/static/ assets are cache-first (their URL changes whenever the content does).
   - Only successful (200, same-origin, non-redirected) responses are ever stored. Old caches are deleted on activate.
   - Stale-cache safety: unhashed files (icons, manifest) are stale-while-revalidate, never cache-first forever; a 5xx
     page from the host (e.g. Render waking up) falls back to the last good copy instead of replacing the app with an
     error page; the hashed-asset cache is capped (oldest entries dropped) so deploys can't grow it without bound.
     Bump VERSION when this file's behaviour changes: it also drops every older cache.
   - The page tells us which assets it loaded (message below) so the very first visit is fully available offline,
     even though those requests happened before this worker controlled the page. */
const VERSION = "v9";
const MAX_ASSETS = 150; // hashed files from older deploys pile up otherwise
const SHELL = `shell-${VERSION}`;
const ASSETS = `assets-${VERSION}`;
const OFFLINE_URL = "/offline.html";
const PRECACHE = [OFFLINE_URL, "/", "/terms", "/privacy", "/model", "/track-record", "/icon-192.png"];

const cacheable = (res) => res && res.ok && res.status === 200 && res.type === "basic" && !res.redirected;

async function trim(cache) {
  const keys = await cache.keys(); // insertion order: oldest first
  await Promise.all(keys.slice(0, Math.max(keys.length - MAX_ASSETS, 0)).map((k) => cache.delete(k)));
}

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
    })).then(() => trim(c))),
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
          return res;
        }
        if (res.status >= 500) {
          // the host answered with an error page (cold start, bad deploy): prefer the last good copy of this page
          const last = await caches.match(req, { ignoreSearch: true });
          if (last) return last;
        }
        return res;
      } catch {
        return (await caches.match(req, { ignoreSearch: true })) || (await caches.match("/")) || (await caches.match(OFFLINE_URL));
      }
    })());
    return;
  }

  if (url.pathname.startsWith("/_next/static/")) {
    // content-hashed URL: the bytes never change, so cache-first is safe
    event.respondWith((async () => {
      const hit = await caches.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (cacheable(res)) {
        const c = await caches.open(ASSETS);
        await c.put(req, res.clone());
        await trim(c);
      }
      return res;
    })());
    return;
  }

  if (url.pathname.startsWith("/icon") || url.pathname === "/apple-touch-icon.png" || url.pathname === "/manifest.webmanifest") {
    // NOT content-hashed: serve the saved copy for speed but always refresh it in the background, so a changed icon or
    // manifest is picked up on the next load instead of never
    event.respondWith((async () => {
      const c = await caches.open(ASSETS);
      const hit = await c.match(req);
      const refresh = fetch(req).then(async (res) => { if (cacheable(res)) await c.put(req, res.clone()); return res; });
      if (hit) { event.waitUntil(refresh.catch(() => undefined)); return hit; }
      return refresh;
    })());
  }
});
