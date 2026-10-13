const CACHE = "lmp-v2";
const SHELL = ["/", "/css/app.css", "/js/api.js", "/js/queue.js", "/js/library.js", "/js/player.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Network-first for API calls and media streams
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(fetch(e.request).catch(() => new Response(
      JSON.stringify({detail: "接続できません。通信状態を確認して再試行してください"}),
      {status: 503, headers: {"Content-Type": "application/json"}},
    )));
    return;
  }

  // Cache-first for shell assets
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request).then((res) => {
      if (res.ok && e.request.method === "GET") {
        caches.open(CACHE).then((c) => c.put(e.request, res.clone()));
      }
      return res;
    }))
  );
});
