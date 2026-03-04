// Thin loader so the app can be split into smaller files under `assets/app/`.
(function () {
  try {
    var cfg = window.__VODCASTS__ || {};
    var base = String(cfg.basePath || "/");
    if (!base.startsWith("/")) base = "/" + base;
    if (!base.endsWith("/")) base = base + "/";
    var src = base + "assets/app/index.js";
    var s = document.createElement("script");
    s.type = "module";
    s.src = src;
    document.head.appendChild(s);
  } catch (_e) {}
})();

