function cleanParams(params) {
  const p = params && typeof params === "object" ? params : {};
  const out = {};
  for (const [k, v0] of Object.entries(p)) {
    const key = String(k || "").trim();
    if (!key) continue;
    const v = v0;
    if (v == null) continue;
    if (typeof v === "string") out[key] = v.slice(0, 120);
    else if (typeof v === "number" && Number.isFinite(v)) out[key] = v;
    else if (typeof v === "boolean") out[key] = v;
  }
  return out;
}

function hasGtag() {
  try {
    return typeof window !== "undefined" && typeof window.gtag === "function";
  } catch {
    return false;
  }
}

export function trackEvent(name, params = {}) {
  const ev = String(name || "").trim();
  if (!ev) return;
  if (!hasGtag()) return;
  try {
    window.gtag("event", ev, cleanParams(params));
  } catch {}
}

export function trackPageView(pathname) {
  if (!hasGtag()) return;
  try {
    const page_path = String(pathname || window.location.pathname || "/");
    window.gtag("event", "page_view", { page_path });
  } catch {}
}

