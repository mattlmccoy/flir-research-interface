/* FLIR Research Interface site worker: network-first for the app shell, cache fallback offline.
   Operator traffic (localhost) is never intercepted. A styled offline.html is precached on install
   so that even a first-ever visit while offline shows a branded page pointing at the local operator
   (http://127.0.0.1:8000), instead of the browser's raw "no internet" error. */
const CACHE = "fri-shell-v2";
const OFFLINE = `${self.registration.scope}offline.html`;

self.addEventListener("install", (e) => {
  // Precache the offline fallback so it is available with no prior network hit.
  e.waitUntil(caches.open(CACHE).then((c) => c.add(OFFLINE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return; // operator calls pass through
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => {
        if (hit) return hit;
        if (e.request.mode === "navigate") {
          // cached app shell first (full app works offline against the local operator), else the
          // branded offline page pointing at the operator.
          return caches.match(`${self.registration.scope}index.html`)
            .then((shell) => shell || caches.match(OFFLINE));
        }
        return undefined;
      })),
  );
});
