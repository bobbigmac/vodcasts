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

function devBuilderPlugin() {
  const projectRoot = process.cwd();
  const distRoot = path.join(projectRoot, "dist");
  const feedsConfig = process.env.VOD_FEEDS || "feeds/dev.md";
  const cacheDir = process.env.VOD_CACHE || "cache/dev";

  let running = false;
  let queued = null;
  let serverRef = null;

  function sendFullReload() {
    serverRef?.ws?.send({ type: "full-reload" });
  }

  async function buildSite({ alsoUpdateFeeds }) {
    if (running) {
      queued = queued || { alsoUpdateFeeds: false };
      queued.alsoUpdateFeeds = queued.alsoUpdateFeeds || alsoUpdateFeeds;
      return;
    }
    running = true;
    try {
      if (alsoUpdateFeeds) {
        await run("python3", ["-m", "scripts.update_feeds", "--feeds", feedsConfig, "--cache", cacheDir, "--quiet"], {
          cwd: projectRoot,
        });
      }
      await run(
        "python3",
        ["-m", "scripts.build_site", "--feeds", feedsConfig, "--cache", cacheDir, "--base-path", "/", "--out", distRoot],
        { cwd: projectRoot }
      );
      sendFullReload();
    } finally {
      running = false;
      const next = queued;
      queued = null;
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
        "scripts/**",
        "feeds/**",
        "video-sources*.json",
        normalize(feedsConfig),
        normalize(cacheDir) + "/**",
      ];
      server.watcher.add(watch);

      buildSite({ alsoUpdateFeeds: false }).catch((e) => server.config.logger.error(String(e?.message || e)));

      server.watcher.on("all", async (event, file) => {
        if (!file) return;
        const f = path.resolve(file);
        const rel = normalize(path.relative(projectRoot, f));
        if (rel.startsWith("dist/")) return;
        if (event !== "add" && event !== "change" && event !== "unlink") return;

        const alsoUpdateFeeds = rel === normalize(feedsConfig);
        await buildSite({ alsoUpdateFeeds }).catch((e) => server.config.logger.error(String(e?.message || e)));
      });
    },
  };
}

export default defineConfig({
  root: "dist",
  plugins: [devBuilderPlugin(), feedProxyPlugin()],
  server: {
    port: 8000,
    strictPort: true,
    open: "/",
  },
});
