// Ported from `video-podcasts/feed-cache.js` (Cache API + heuristic TTL).

const CACHE_NAME = "vodcasts-feeds-v1";
const DEAD_FEED_SKIP_DAYS = 3;
const ONE_YEAR_MS = 365 * 24 * 60 * 60 * 1000;
const PROB_DUE_THRESHOLD = 0.65;
const SKIP_STORAGE_KEY = "vodcasts_skip_v1";
const MAX_CONCURRENT = 2;
const MEMORY_CACHE_MAX_AGE_MS = 4 * 60 * 60 * 1000;

const memoryCache = new Map();
const inFlightByKey = new Map();
const fetchQueue = [];
let inFlight = 0;

function cacheKey(url) {
  try {
    return new URL(url, self.location?.href || "https://localhost/").href;
  } catch {
    return String(url);
  }
}

function getSkipMap() {
  try {
    const raw = localStorage.getItem(SKIP_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function setSkip(url, untilMs) {
  const m = getSkipMap();
  m[url] = untilMs;
  try {
    localStorage.setItem(SKIP_STORAGE_KEY, JSON.stringify(m));
  } catch {}
}

function getSkipUntil(url) {
  return getSkipMap()[url] || 0;
}

function extractEntryDates(xmlText) {
  const dates = [];
  try {
    const doc = new DOMParser().parseFromString(xmlText, "text/xml");
    const isAtom = !!doc.querySelector("feed > entry");
    const items = isAtom ? doc.querySelectorAll("feed > entry") : doc.querySelectorAll("channel > item");
    for (const item of items) {
      const dateStr =
        (item.querySelector("pubDate")?.textContent || "").trim() ||
        (item.querySelector("published")?.textContent || "").trim() ||
        (item.querySelector("updated")?.textContent || "").trim();
      if (dateStr) {
        const d = new Date(dateStr);
        if (!Number.isNaN(d.valueOf())) dates.push(d.getTime());
      }
    }
  } catch {}
  return dates.sort((a, b) => b - a);
}

function computeProbDue(lastEntryDates) {
  if (!lastEntryDates.length) return 1;
  const now = Date.now();
  const mostRecent = lastEntryDates[0];
  if (lastEntryDates.length < 2) {
    const daysSince = (now - mostRecent) / (24 * 60 * 60 * 1000);
    return Math.min(1, daysSince / 7);
  }
  const gaps = [];
  for (let i = 0; i < lastEntryDates.length - 1; i++) {
    gaps.push(lastEntryDates[i] - lastEntryDates[i + 1]);
  }
  const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  if (avgGap <= 0) return 1;
  const timeSinceLast = now - mostRecent;
  return Math.min(1, timeSinceLast / avgGap);
}

function runNext() {
  if (inFlight >= MAX_CONCURRENT || fetchQueue.length === 0) return;
  const { key, url, resolve, reject } = fetchQueue.shift();
  inFlight += 1;
  doFetch(url)
    .then((text) => {
      resolve(text);
      return text;
    })
    .catch(reject)
    .finally(() => {
      inFlight -= 1;
      inFlightByKey.delete(key);
      runNext();
    });
}

async function doFetch(url) {
  const key = cacheKey(url);
  const now = Date.now();

  const mem = memoryCache.get(key);
  if (mem && now - mem.at < MEMORY_CACHE_MAX_AGE_MS) return mem.text;

  const skipUntil = getSkipUntil(key);
  if (skipUntil && now < skipUntil && mem) return mem.text;

  let cache;
  try {
    cache = await caches.open(CACHE_NAME);
  } catch {
    if (mem) return mem.text;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`fetch ${res.status}`);
    return res.text();
  }

  const req = new Request(key, { method: "GET" });
  let cached;
  try {
    cached = await cache.match(req);
  } catch {
    cached = null;
  }

  if (cached) {
    const text = await cached.text();
    const metaRaw = cached.headers.get("X-Feed-Meta");
    if (metaRaw) {
      try {
        const meta = JSON.parse(metaRaw);
        const dates = meta.lastEntryDates || [];
        if (dates.length) {
          const mostRecent = dates[0];
          if (now - mostRecent > ONE_YEAR_MS) {
            setSkip(key, now + DEAD_FEED_SKIP_DAYS * 24 * 60 * 60 * 1000);
            memoryCache.set(key, { text, at: now });
            return text;
          }
          const probDue = computeProbDue(dates);
          if (probDue < PROB_DUE_THRESHOLD) {
            memoryCache.set(key, { text, at: now });
            return text;
          }
        }
      } catch {}
    } else {
      const cachedAt = parseInt(cached.headers.get("X-Cached-At") || "0", 10);
      if (cachedAt && now - cachedAt < 2 * 60 * 60 * 1000) {
        memoryCache.set(key, { text, at: now });
        return text;
      }
    }
  }

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetch ${res.status}`);
  const text = await res.text();
  const dates = extractEntryDates(text);
  const meta = { lastEntryDates: dates, fetchedAt: now };
  try {
    await cache.put(
      req,
      new Response(text, {
        headers: new Headers({
          "Content-Type": res.headers.get("Content-Type") || "text/xml",
          "X-Cached-At": now.toString(),
          "X-Feed-Meta": JSON.stringify(meta),
        }),
      })
    );
  } catch {}
  memoryCache.set(key, { text, at: now });
  return text;
}

export async function fetchCached(url) {
  const key = cacheKey(url);
  const now = Date.now();

  const mem = memoryCache.get(key);
  if (mem && now - mem.at < MEMORY_CACHE_MAX_AGE_MS) return mem.text;

  const skipUntil = getSkipUntil(key);
  if (skipUntil && now < skipUntil && mem) return mem.text;

  const existing = inFlightByKey.get(key);
  if (existing) return existing;

  const promise = new Promise((resolve, reject) => {
    fetchQueue.push({ key, url, resolve, reject });
    runNext();
  });
  inFlightByKey.set(key, promise);
  return promise;
}

export async function clearCache() {
  try {
    const exists = await caches.has(CACHE_NAME);
    if (exists) await caches.delete(CACHE_NAME);
  } catch {}
  try {
    localStorage.removeItem(SKIP_STORAGE_KEY);
  } catch {}
  memoryCache.clear();
}

