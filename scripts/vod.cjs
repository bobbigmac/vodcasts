#!/usr/bin/env node
"use strict";

const path = require("path");
const fs = require("fs");
const { spawnSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const STATE_FILE = path.join(ROOT, ".vodcasts-env");
const PY = process.platform === "win32" ? "python" : "python3";

function die(msg) {
  console.error("error:", msg);
  process.exit(2);
}

function canonEnv(v) {
  if (!v) return v;
  switch (v) {
    case "prod":
    case "main":
    case "full":
      return "complete";
    default:
      return v;
  }
}

function activeEnv() {
  if (process.env.VOD_ENV) {
    return canonEnv(process.env.VOD_ENV);
  }
  if (fs.existsSync(STATE_FILE)) {
    const v = fs.readFileSync(STATE_FILE, "utf8").replace(/\r?\n/g, "").trim();
    if (v) return canonEnv(v);
  }
  console.error(
    "warning: VOD_ENV is not set; defaulting to 'dev'. Run: yarn use dev|church|tech|complete"
  );
  return "dev";
}

function resolveFeeds(envName) {
  envName = canonEnv(envName);
  const f = path.join(ROOT, "feeds", `${envName}.md`);
  if (!fs.existsSync(f)) die(`unknown env '${envName}' (missing ${f})`);
  return f;
}

function resolveCache(envName) {
  envName = canonEnv(envName);
  return path.join(ROOT, "cache", envName);
}

function logEnv(envName, feeds, cache) {
  console.error(
    `[vodcasts] env=${envName} feeds=${path.basename(feeds)} cache=${path.basename(cache)}`
  );
}

function ensureDir(p) {
  if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
}

const cmd = process.argv[2] || "";
const rest = process.argv.slice(3);

switch (cmd) {
  case "use": {
    const envName = canonEnv(rest[0]);
    if (!envName) die("usage: yarn use <dev|church|tech|complete>");
    const feeds = resolveFeeds(envName);
    ensureDir(path.join(ROOT, "cache", envName));
    fs.writeFileSync(STATE_FILE, envName + "\n");
    console.error("Selected:", envName, `(${feeds})`);
    console.error("Tip: to use an env var instead of the state file: export VOD_ENV=" + envName);
    break;
  }

  case "export": {
    console.log("export VOD_ENV=" + activeEnv());
    break;
  }

  case "update":
  case "build":
  case "dev": {
    const envName = activeEnv();
    const feeds = resolveFeeds(envName);
    const cache = resolveCache(envName);
    ensureDir(cache);
    logEnv(envName, feeds, cache);

    if (cmd === "update") {
      const r = spawnSync(
        PY,
        ["-m", "scripts.update_feeds", "--feeds", feeds, "--cache", cache, ...rest],
        { stdio: "inherit", cwd: ROOT }
      );
      process.exit(r.status ?? 1);
    } else if (cmd === "build") {
      spawnSync(PY, ["-m", "scripts.update_feeds", "--feeds", feeds, "--cache", cache, "--quiet"], {
        stdio: "inherit",
        cwd: ROOT,
      });
      const basePath = process.env.VOD_BASE_PATH || "/";
      const extraBuildArgs = rest.includes("--fetch-missing-feeds") ? [] : ["--fetch-missing-feeds"];
      const r = spawnSync(
        PY,
        [
          "-m",
          "scripts.build_site",
          "--feeds",
          feeds,
          "--cache",
          cache,
          "--out",
          path.join(ROOT, "dist"),
          "--base-path",
          basePath,
          ...extraBuildArgs,
          ...rest,
        ],
        { stdio: "inherit", cwd: ROOT }
      );
      process.exit(r.status ?? 1);
    } else {
      process.env.VOD_FEEDS = feeds;
      process.env.VOD_CACHE = cache;
      const viteBin = path.join(ROOT, "node_modules", "vite", "bin", "vite.js");
      const r = spawnSync(process.execPath, [viteBin, "--config", path.join(ROOT, "vite.config.js"), ...rest], {
        stdio: "inherit",
        cwd: ROOT,
      });
      process.exit(r.status ?? 1);
    }
    break;
  }

  case "":
  case "-h":
  case "--help":
  case "help":
    console.error(`vodcasts helper

Commands:
  yarn use <env>    Select env (persists in .vodcasts-env)
  node scripts/vod.cjs export  Print an export line for the current env
  yarn update       Update cached feeds for selected env
  yarn build        Build site for selected env
  yarn dev          Run dev server for selected env

Env vars:
  VOD_ENV           Overrides .vodcasts-env (non-persistent)
  VOD_BASE_PATH     Used by 'yarn build' (default: /)
`);
    break;

  default:
    die(`unknown command: ${cmd} (try: yarn help)`);
}
