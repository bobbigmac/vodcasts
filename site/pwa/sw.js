/* Simple offline support for vodcasts.
   Scope is the site base path (service worker is emitted at /<base>/sw.js). */

const STATIC_CACHE = "vodcasts-static-v1";
const DATA_CACHE = "vodcasts-data-v1";

function urlFor(path) {
  return new URL(path, self.registration.scope).toString();
}

function isSameOrigin(url) {
  try {
    const scope = new URL(self.registration.scope);
    return url.origin === scope.origin;
  } catch {
    return false;
  }
}

function basePathname() {
  try {
    return new URL(self.registration.scope).pathname;
  } catch {
    return "/";
  }
}

function shouldCacheUrl(url) {
  const p = url.pathname || "";
  if (p.endsWith("/sw.js")) return false;
  return (
    p.endsWith("/") ||
    p.endsWith(".html") ||
    p.includes("/assets/") ||
    p.endsWith(".json") ||
    p.endsWith(".webmanifest") ||
    p.endsWith(".xml")
  );
}

const PRECACHE = [
  "",
  "index.html",
  "manifest.webmanifest",
  "site.json",
  "video-sources.json",
  "feed-manifest.json",

  "assets/style.css",
  "assets/themes.css",
  "assets/app.js",
  "assets/vendor/hls.min.js",
  "assets/icon-192.png",
  "assets/icon-512.png",
  "assets/apple-touch-icon.png",

  // ESM app modules.
  "assets/app/index.js",
  "assets/app/main/app.js",
  "assets/app/main/boot.js",
  "assets/app/main/controls.js",
  "assets/app/main/route.js",
  "assets/app/player/player.js",
  "assets/app/runtime/analytics.js",
  "assets/app/runtime/env.js",
  "assets/app/runtime/log.js",
  "assets/app/runtime/pwa.js",
  "assets/app/runtime/vendor.js",
  "assets/app/state/history.js",
  "assets/app/ui/chapters.js",
  "assets/app/ui/details.js",
  "assets/app/ui/guide.js",
  "assets/app/ui/history.js",
  "assets/app/ui/icons.js",
  "assets/app/ui/log.js",
  "assets/app/ui/long_press.js",
  "assets/app/ui/search.js",
  "assets/app/ui/status_toast.js",
  "assets/app/ui/subtitle_box.js",
  "assets/app/ui/takeover/audio_takeover.js",
  "assets/app/ui/takeover/captions_takeover.js",
  "assets/app/ui/takeover/chapters_nav_takeover.js",
  "assets/app/ui/takeover/panel_takeover.js",
  "assets/app/ui/takeover/random_takeover.js",
  "assets/app/ui/takeover/share_takeover.js",
  "assets/app/ui/takeover/shuffle_takeover.js",
  "assets/app/ui/takeover/skip_takeover.js",
  "assets/app/ui/takeover/sleep_takeover.js",
  "assets/app/ui/takeover/speed_takeover.js",
  "assets/app/ui/takeover/theme_takeover.js",
  "assets/app/vod/feed_cache.js",
  "assets/app/vod/feed_parse.js",
  "assets/app/vod/sources.js",
  "assets/app/vod/timed_comments.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE.map(urlFor)))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k.startsWith("vodcasts-") && ![STATIC_CACHE, DATA_CACHE].includes(k)).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (!req || req.method !== "GET") return;

  const url = new URL(req.url);
  if (!isSameOrigin(url)) return;

  const base = basePathname();
  const isFeedXml = url.pathname.startsWith(base + "data/feeds/") && url.pathname.endsWith(".xml");
  const cacheName = isFeedXml ? DATA_CACHE : STATIC_CACHE;

  // SPA navigation: serve the shell when offline / cached.
  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        const cache = await caches.open(STATIC_CACHE);
        const shell = await cache.match(urlFor("index.html"));
        try {
          const fresh = await fetch(req);
          if (fresh && fresh.ok) {
            try {
              cache.put(urlFor("index.html"), fresh.clone());
            } catch {}
            return fresh;
          }
        } catch {}
        return shell || fetch(req);
      })()
    );
    return;
  }

  if (!shouldCacheUrl(url)) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(cacheName);
      const cached = await cache.match(req);
      if (cached) {
        event.waitUntil(
          fetch(req)
            .then((resp) => {
              if (resp && resp.ok) return cache.put(req, resp.clone());
            })
            .catch(() => {})
        );
        return cached;
      }

      try {
        const resp = await fetch(req);
        if (resp && resp.ok) {
          try {
            await cache.put(req, resp.clone());
          } catch {}
        }
        return resp;
      } catch (e) {
        return cached || Response.error();
      }
    })()
  );
});

