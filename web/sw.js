/* Minimal PWA service worker:
 * - Precaches the app shell
 * - Network-first for navigations
 * - Cache-first for static assets (CSS/JS/images)
 * - Never caches /api or /uploads
 */

const CACHE_VERSION = "v89";
const SHELL_CACHE = `verifika2-shell-${CACHE_VERSION}`;
const RUNTIME_CACHE = `verifika2-runtime-${CACHE_VERSION}`;
const FONTS_CACHE = `verifika2-fonts-${CACHE_VERSION}`;

const SHELL_URLS = [
  "/",
  "/index.html",
  "/styles.css?v=171",
  "/ui-foundation.js?v=3",
  "/app-auth.js?v=10",
  "/app-routing.js?v=7",
  "/app.js?v=462",
  "/manifest.webmanifest?v=17",
  "/assets/verifika2/verifika2_mark.svg",
  "/assets/verifika2/verifika2_badge_gold.svg",
  "/assets/verifika2/verifika2_badge_silver.svg",
  "/assets/verifika2/verifika2_badge_carbon.svg",
  "/icons/ios/v28/icon-192.png",
  "/icons/ios/v28/icon-512.png",
  "/icons/ios/v28/apple-touch-icon-180.png",
];

const isSameOrigin = (url) => {
  try {
    return new URL(url, self.location.href).origin === self.location.origin;
  } catch {
    return false;
  }
};

const isFontRequest = (url) => {
  try {
    const u = new URL(url, self.location.href);
    return u.origin === "https://fonts.googleapis.com" || u.origin === "https://fonts.gstatic.com";
  } catch {
    return false;
  }
};

const isCacheablePath = (pathname) => {
  if (!pathname) return false;
  if (pathname.startsWith("/api/")) return false;
  if (pathname.startsWith("/uploads/")) return false;
  return true;
};

const normalizeCacheKey = (request) => {
  // Keep versioned URLs for CSS/JS so deployments (e.g. app.js?v=378) bust caches reliably.
  // We only normalize images/icons where query params are usually irrelevant.
  try {
    const url = new URL(request.url);
    if (!isSameOrigin(url.href)) return request;
    const pathname = url.pathname || "";
    if (!isCacheablePath(pathname)) return request;
    if (/\.(css|js|webmanifest)$/i.test(pathname)) return request;
    if (/\.(png|jpg|jpeg|svg)$/i.test(pathname)) {
      return new Request(url.origin + pathname, {
        method: request.method,
        headers: request.headers,
        credentials: "same-origin",
      });
    }
    return request;
  } catch {
    return request;
  }
};

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      await cache.addAll(SHELL_URLS);
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if ((key.startsWith("liv-") || key.startsWith("verifika2-")) && ![SHELL_CACHE, RUNTIME_CACHE].includes(key)) {
            return caches.delete(key);
          }
          return null;
        })
      );
      await self.clients.claim();
      try {
        const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
        clients.forEach((client) => {
          try {
            client.postMessage({ type: "SW_ACTIVATED", version: CACHE_VERSION });
          } catch {}
        });
      } catch {}
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const isFonts = isFontRequest(url.href);
  if (!isFonts) {
    if (!isSameOrigin(url.href)) return;
    if (!isCacheablePath(url.pathname)) return;
  }

  const isNavigation = !isFonts && (req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html"));
  const key = isFonts ? req : normalizeCacheKey(req);

  if (isNavigation) {
    // Network-first so we always get the latest app shell when online.
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(req);
          const cache = await caches.open(SHELL_CACHE);
          cache.put("/index.html", fresh.clone());
          return fresh;
        } catch {
          const cache = await caches.open(SHELL_CACHE);
          return (await cache.match("/index.html")) || (await cache.match("/")) || Response.error();
        }
      })()
    );
    return;
  }

  if (isFonts) {
    // Cache-first for Google Fonts to speed up PWA (iOS/Android).
    event.respondWith(
      (async () => {
        const cache = await caches.open(FONTS_CACHE);
        const cached = await cache.match(req);
        if (cached) return cached;
        const resp = await fetch(req);
        if (resp) {
          try {
            cache.put(req, resp.clone());
          } catch {}
        }
        return resp;
      })()
    );
    return;
  }

  // Static assets: cache-first with runtime refresh.
  event.respondWith(
    (async () => {
      const cache = await caches.open(RUNTIME_CACHE);
      const cached = await cache.match(key);
      if (cached) return cached;
      const resp = await fetch(req);
      if (resp && resp.ok) {
        try {
          cache.put(key, resp.clone());
        } catch {}
      }
      return resp;
    })()
  );
});
