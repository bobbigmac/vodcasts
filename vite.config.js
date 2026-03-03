import { defineConfig } from "vite";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import fs from "node:fs";
import { spawn } from "node:child_process";
import { URL } from "node:url";

function run(cmd, args, opts) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: "inherit", ...opts });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited with ${code}`));
    });
  });
}

function normalize(p) {
  return p.split(path.sep).join("/");
}

function fetchUrl(urlStr, { maxRedirects = 5 } = {}) {
  return new Promise((resolve, reject) => {
    let url;
    try {
      url = new URL(urlStr);
    } catch {
      reject(new Error("bad url"));
      return;
    }

    const mod = url.protocol === "https:" ? https : http;
    const req = mod.request(
      url,
      {
        method: "GET",
        headers: {
          "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
          Accept: "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
          "Accept-Language": "en-US,en;q=0.8",
        },
      },
      (res) => {
        const status = res.statusCode || 0;
        const loc = res.headers.location;
        if (status >= 300 && status < 400 && loc && maxRedirects > 0) {
          res.resume();
          const next = new URL(loc, url).toString();
          fetchUrl(next, { maxRedirects: maxRedirects - 1 }).then(resolve, reject);
          return;
        }

        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const body = Buffer.concat(chunks);
          resolve({
            status,
            headers: res.headers,
            body,
          });
        });
      }
    );

    req.on("error", reject);
    req.end();
  });
}

function feedProxyPlugin() {
  return {
    name: "vodcasts-feed-proxy",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        try {
          if (!req.url?.startsWith("/__feed")) return next();
          const u = new URL(req.url, "http://local/");
          const target = u.searchParams.get("url") || "";
          if (!/^https?:\/\//i.test(target)) {
            res.statusCode = 400;
            res.setHeader("Content-Type", "text/plain; charset=utf-8");
            res.end("missing/invalid url");
            return;
          }

          const out = await fetchUrl(target);
          res.statusCode = out.status || 502;
          res.setHeader("Access-Control-Allow-Origin", "*");
          res.setHeader("Cache-Control", "no-store");

          const ct = String(out.headers["content-type"] || "");
          res.setHeader("Content-Type", ct || "application/xml; charset=utf-8");
          res.end(out.body);
        } catch (e) {
          res.statusCode = 502;
          res.setHeader("Content-Type", "text/plain; charset=utf-8");
          res.end(String(e?.message || e || "proxy error"));
        }
      });
    },
  };
}

function noCacheDevPlugin() {
  return {
    name: "vodcasts-no-cache-dev",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        // Avoid interfering with WS/HMR upgrades.
        if (req.headers.upgrade) return next();
        res.setHeader("Cache-Control", "no-store, max-age=0, must-revalidate");
        res.setHeader("Pragma", "no-cache");
        res.setHeader("Expires", "0");
        res.setHeader("Surrogate-Control", "no-store");
        next();
      });
    },
  };
}

function devBuilderPlugin() {
  const projectRoot = process.cwd();
  const distRoot = path.join(projectRoot, "dist");
  const feedsConfig = process.env.VOD_FEEDS || "feeds/dev.md";
  const cacheDir = process.env.VOD_CACHE || "cache/dev";
  const feedsConfigAbs = path.resolve(projectRoot, feedsConfig);
  const feedsConfigRel = normalize(path.relative(projectRoot, feedsConfigAbs));
  const cacheDirAbs = path.resolve(projectRoot, cacheDir);
  const cacheDirRel = normalize(path.relative(projectRoot, cacheDirAbs));

  let running = false;
  let queued = null;
  let debounceTo = null;
  let serverRef = null;

  function sendFullReload() {
    serverRef?.ws?.send({ type: "full-reload" });
  }

  const py = process.platform === "win32" ? "python" : "python3";

  function isIgnoredPath(rel) {
    if (!rel) return true;
    if (rel.startsWith("dist/")) return true;
    if (rel.includes("/__pycache__/")) return true;
    if (rel.endsWith(".pyc")) return true;
    if (rel.includes("/.git/")) return true;
    if (rel.includes("/node_modules/")) return true;
    if (rel === "yarn.lock" || rel.endsWith("/yarn.lock")) return true;
    if (rel === "package-lock.json" || rel.endsWith("/package-lock.json")) return true;
    if (rel === "pnpm-lock.yaml" || rel.endsWith("/pnpm-lock.yaml")) return true;
    return false;
  }

  function isRelevantPath(rel) {
    if (!rel) return false;
    if (rel.startsWith("site/assets/")) return true;
    if (rel.startsWith("site/templates/")) return true;
    if (rel.startsWith("scripts/")) return true;
    if (rel.startsWith("feeds/")) return true;
    if (rel === feedsConfigRel) return true;
    // Optional: if someone edits the cache manually, rebuild once.
    if (rel.startsWith(cacheDirRel + "/feeds/") && rel.endsWith(".xml")) return true;
    return false;
  }

  function copyIfNewer(srcAbs, dstAbs) {
    try {
      const st = fs.statSync(srcAbs);
      if (!st.isFile()) return false;
      let dst = null;
      try {
        dst = fs.statSync(dstAbs);
      } catch {}
      if (dst && dst.isFile() && dst.size === st.size && dst.mtimeMs >= st.mtimeMs) return false;
      fs.mkdirSync(path.dirname(dstAbs), { recursive: true });
      fs.copyFileSync(srcAbs, dstAbs);
      return true;
    } catch {
      return false;
    }
  }

  function unlinkIfExists(dstAbs) {
    try {
      fs.unlinkSync(dstAbs);
      return true;
    } catch {
      return false;
    }
  }

  function fastAssetSync({ event, rel, abs }) {
    if (!rel.startsWith("site/assets/")) return false;
    const sub = rel.slice("site/assets/".length);
    const dstAbs = path.join(distRoot, "assets", sub);
    if (event === "unlink") return unlinkIfExists(dstAbs);
    if (event === "add" || event === "change") return copyIfNewer(abs, dstAbs);
    return false;
  }

  function scheduleBuild(opts) {
    if (running) {
      queued = queued || { alsoUpdateFeeds: false, clean: false, copyFeeds: false, copyAssets: false };
      queued.alsoUpdateFeeds = queued.alsoUpdateFeeds || !!opts?.alsoUpdateFeeds;
      queued.clean = queued.clean || !!opts?.clean;
      queued.copyFeeds = queued.copyFeeds || !!opts?.copyFeeds;
      queued.copyAssets = queued.copyAssets || !!opts?.copyAssets;
      return;
    }
    if (debounceTo) clearTimeout(debounceTo);
    const next = opts || { alsoUpdateFeeds: false, clean: false, copyFeeds: false, copyAssets: false };
    queued = queued || { alsoUpdateFeeds: false, clean: false, copyFeeds: false, copyAssets: false };
    queued.alsoUpdateFeeds = queued.alsoUpdateFeeds || !!next.alsoUpdateFeeds;
    queued.clean = queued.clean || !!next.clean;
    queued.copyFeeds = queued.copyFeeds || !!next.copyFeeds;
    queued.copyAssets = queued.copyAssets || !!next.copyAssets;
    debounceTo = setTimeout(() => {
      debounceTo = null;
      const q = queued;
      queued = null;
      buildSite(q).catch((e) => serverRef?.config?.logger?.error?.(String(e?.message || e)));
    }, 120);
  }

  async function buildSite({ alsoUpdateFeeds = false, clean = false, copyFeeds = false, copyAssets = true } = {}) {
    if (running) {
      scheduleBuild({ alsoUpdateFeeds, clean, copyFeeds, copyAssets });
      return;
    }
    running = true;
    try {
      if (alsoUpdateFeeds) {
        await run(py, ["-B", "-m", "scripts.update_feeds", "--feeds", feedsConfig, "--cache", cacheDir, "--quiet"], {
          cwd: projectRoot,
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
        });
      }
      await run(
        py,
        [
          "-B",
          "-m",
          "scripts.build_site",
          "--feeds",
          feedsConfig,
          "--cache",
          cacheDir,
          "--base-path",
          "/",
          "--out",
          distRoot,
          ...(clean ? ["--clean"] : ["--no-clean"]),
          ...(copyAssets ? ["--copy-assets"] : ["--no-copy-assets"]),
          ...(copyFeeds ? ["--copy-feeds"] : ["--no-copy-feeds"]),
          "--no-fetch-missing-feeds",
        ],
        { cwd: projectRoot, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } }
      );
      sendFullReload();
    } finally {
      running = false;
      const next = queued;
      queued = null;
      if (debounceTo) {
        clearTimeout(debounceTo);
        debounceTo = null;
      }
      if (next) await buildSite(next);
    }
  }

  return {
    name: "vodcasts-dev-builder",
    configureServer(server) {
      serverRef = server;
      const watch = [
        "site/assets/**",
        "site/templates/**",
        "scripts/**/*.py",
        "scripts/**/*.js",
        "feeds/**",
        feedsConfigAbs,
        normalize(cacheDirAbs) + "/feeds/*.xml",
      ];
      server.watcher.add(watch);

      // Build once on startup, and update the feed cache so the guide isn't empty
      // when the local cache doesn't match the active feeds config.
      const hasIndex = fs.existsSync(path.join(distRoot, "index.html"));
      scheduleBuild({ alsoUpdateFeeds: true, clean: !hasIndex, copyFeeds: true, copyAssets: true });

      server.watcher.on("all", async (event, file) => {
        if (!file) return;
        const f = path.resolve(file);
        const rel = normalize(path.relative(projectRoot, f));
        if (isIgnoredPath(rel)) return;
        if (!isRelevantPath(rel)) return;
        if (event !== "add" && event !== "change" && event !== "unlink") return;

        // Fast path: asset changes just sync into dist/ and let Vite handle reload/HMR.
        if (fastAssetSync({ event, rel, abs: f })) return;

        const isFeedsCfg = rel === feedsConfigRel;
        const isCacheFeed = rel.startsWith(cacheDirRel + "/feeds/") && rel.endsWith(".xml");
        const isTemplates = rel.startsWith("site/templates/");
        const alsoUpdateFeeds = isFeedsCfg;
        // Only do heavyweight copies/cleaning when feed inputs changed.
        scheduleBuild({
          alsoUpdateFeeds,
          clean: isFeedsCfg,
          copyFeeds: alsoUpdateFeeds || isCacheFeed,
          copyAssets: isTemplates,
        });
      });
    },
  };
}

export default defineConfig({
  root: "dist",
  plugins: [noCacheDevPlugin(), devBuilderPlugin(), feedProxyPlugin()],
  server: {
    port: 8000,
    strictPort: true,
    open: "/",
    watch:
      process.platform === "win32" || process.env.VOD_WATCH_POLL === "1"
        ? { usePolling: true, interval: 750, ignored: ["**/__pycache__/**", "**/*.pyc"] }
        : { ignored: ["**/__pycache__/**", "**/*.pyc"] },
    headers: {
      "Cache-Control": "no-store, max-age=0, must-revalidate",
      Pragma: "no-cache",
      Expires: "0",
      "Surrogate-Control": "no-store",
    },
  },
});
