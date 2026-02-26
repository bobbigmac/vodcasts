function normBasePath(p) {
  let s = String(p || "/");
  if (!s.startsWith("/")) s = "/" + s;
  if (!s.endsWith("/")) s = s + "/";
  return s;
}

export function getEnv() {
  const cfg = window.__VODCASTS__ || {};
  const basePath = normBasePath(cfg.basePath || "/");
  const site = cfg.site || {};
  return {
    basePath,
    site,
    sourcesUrl: basePath + "video-sources.json",
    feedManifestUrl: basePath + "feed-manifest.json",
    isDev: !!(import.meta && import.meta.hot),
    // Dev-only feed proxy (Vite); in prod this is typically absent.
    feedProxy: basePath + "__feed?url=",
  };
}
