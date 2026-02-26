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

  const feed = segs[0] || sp.get("feed") || sp.get("channel") || sp.get("c") || "";
  const ep = segs[1] || sp.get("ep") || sp.get("episode") || sp.get("e") || "";

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
    t: Number.isFinite(t) ? t : null,
  };
}

export function setRouteInUrl({ feed, ep } = {}, { replace = true } = {}) {
  const u = new URL(window.location.href);
  const bp = basePath();
  u.search = "";
  u.hash = "";

  let path = bp;
  if (feed) path += encodeURIComponent(String(feed)) + "/";
  if (feed && ep) path += encodeURIComponent(String(ep)) + "/";
  u.pathname = path;

  const next = u.pathname;
  try {
    if (replace) history.replaceState({}, "", next);
    else history.pushState({}, "", next);
  } catch {}
}

export function buildShareUrl({ feed, ep, t } = {}) {
  const u = new URL(window.location.href);
  const bp = basePath();
  u.search = "";
  u.hash = "";

  let path = bp;
  if (feed) path += encodeURIComponent(String(feed)) + "/";
  if (feed && ep) path += encodeURIComponent(String(ep)) + "/";
  u.pathname = path;

  if (t != null && Number.isFinite(Number(t))) u.hash = `t=${String(Math.max(0, Math.floor(Number(t))))}`;
  return u.toString();
}
