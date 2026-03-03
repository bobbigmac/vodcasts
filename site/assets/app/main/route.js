function parseTimeParam(v) {
  if (v == null) return null;
  let s = String(v).trim();
  if (!s) return null;
  // Allow "180s" in addition to "180"
  if (/^\d+(\.\d+)?s$/i.test(s)) s = s.slice(0, -1);
  if (/^\d+(\.\d+)?$/.test(s)) return Math.max(0, Number(s));
  // Allow hh:mm:ss or mm:ss
  const parts = s.split(":").map((x) => x.trim());
  if (parts.length < 2 || parts.length > 3) return null;
  const nums = parts.map(Number);
  if (nums.some((n) => !Number.isFinite(n))) return null;
  const [a, b, c] = parts.length === 3 ? nums : [0, nums[0], nums[1]];
  return Math.max(0, a * 3600 + b * 60 + c);
}

function normBasePath(p) {
  let s = String(p || "/");
  if (!s.startsWith("/")) s = "/" + s;
  if (!s.endsWith("/")) s = s + "/";
  return s;
}

function basePath() {
  return normBasePath(window.__VODCASTS__?.basePath || "/");
}

function decodeSeg(s) {
  try {
    return decodeURIComponent(String(s || ""));
  } catch {
    return String(s || "");
  }
}

export function getRouteFromUrl() {
  const u = new URL(window.location.href);
  const sp = u.searchParams;
  const bp = basePath();

  // GitHub Pages SPA redirect: /__missing__ served 404.html, which redirects to `/?p=<path>`
  const p = sp.get("p");
  const relPath0 = p != null ? String(p) : null;
  const relPath = relPath0 != null ? relPath0.replace(/^\/+/, "") : u.pathname.startsWith(bp) ? u.pathname.slice(bp.length) : u.pathname.replace(/^\/+/, "");
  const segs = relPath.split("/").filter(Boolean).map(decodeSeg);

  // Support /<feed>/, /<feed>/shows/<show>/, /<feed>/<ep>/; /browse/ for browse-all. Legacy: /feed/<feed>/...
  // Also accept `/show/` (singular) because some older links used that form.
  let feed = "";
  let ep = "";
  let show = "";
  const browse = segs[0] === "browse";
  if (segs[0] === "feed" && segs.length >= 2) {
    feed = segs[1] || "";
    if ((segs[2] === "shows" || segs[2] === "show") && segs[3]) show = segs[3] || "";
    else ep = segs[2] || "";
  } else if (!browse && segs[0]) {
    feed = segs[0] || sp.get("feed") || sp.get("channel") || sp.get("c") || "";
    if ((segs[1] === "shows" || segs[1] === "show") && segs[2]) show = segs[2] || "";
    else ep = segs[1] || sp.get("ep") || sp.get("episode") || sp.get("e") || "";
  }

  const hp = new URLSearchParams(String(u.hash || "").replace(/^#/, ""));
  const t = parseTimeParam(hp.get("t") || hp.get("time") || sp.get("t") || sp.get("time"));

  // If we're coming from 404.html redirect, drop `?p=` and restore the canonical URL.
  if (relPath0 != null) {
    try {
      const canon = new URL(window.location.href);
      canon.search = "";
      canon.pathname = bp + relPath;
      history.replaceState({}, "", canon.pathname + canon.hash);
    } catch {}
  }

  return {
    feed: feed || null,
    ep: ep || null,
    show: show || null,
    t: Number.isFinite(t) ? t : null,
    browse: browse || null,
  };
}

function shouldTrackPageView({ feed, ep } = {}) {
  // Avoid double counting (feed-only then episode) since we also emit explicit select events.
  return !!(feed && ep);
}

export function setRouteInUrl({ feed, ep, show } = {}, { replace = true } = {}) {
  const u = new URL(window.location.href);
  const bp = basePath();
  u.search = "";
  u.hash = "";

  let path = bp;
  if (feed) {
    if (show) path += encodeURIComponent(String(feed)) + "/shows/" + encodeURIComponent(String(show)) + "/";
    else if (ep) path += encodeURIComponent(String(feed)) + "/" + encodeURIComponent(String(ep)) + "/";
    else path += encodeURIComponent(String(feed)) + "/";
  }
  u.pathname = path;

  const next = u.pathname;
  try {
    if (replace) history.replaceState({}, "", next);
    else history.pushState({}, "", next);
  } catch {}

  if (shouldTrackPageView({ feed, ep })) {
    try {
      // Lazy import to keep the router side-effect free when analytics is disabled.
      import("../runtime/analytics.js").then((m) => m.trackPageView(next)).catch(() => {});
    } catch {}
  }
}

export function buildShareUrl({ feed, ep, show, t } = {}) {
  const u = new URL(window.location.href);
  const bp = basePath();
  u.search = "";
  u.hash = "";

  let path = bp;
  if (feed) {
    if (show) path += encodeURIComponent(String(feed)) + "/shows/" + encodeURIComponent(String(show)) + "/";
    else if (ep) path += encodeURIComponent(String(feed)) + "/" + encodeURIComponent(String(ep)) + "/";
    else path += encodeURIComponent(String(feed)) + "/";
  }
  u.pathname = path;

  if (t != null && Number.isFinite(Number(t))) u.hash = `t=${String(Math.max(0, Math.floor(Number(t))))}`;
  return u.toString();
}
