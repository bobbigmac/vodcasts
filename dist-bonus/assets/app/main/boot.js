import { render, html, signal } from "../runtime/vendor.js";
import { getEnv } from "../runtime/env.js";
import { createLogger } from "../runtime/log.js";
import { initPwa } from "../runtime/pwa.js";
import { loadSources } from "../vod/sources.js";
import { createHistoryStore } from "../state/history.js";
import { createPlayerService } from "../player/player.js";
import { App } from "./app.js";
import { getRouteFromUrl } from "./route.js";
import { trackPageView } from "../runtime/analytics.js";

export async function bootApp() {
  const env = getEnv();
  const log = createLogger();
  initPwa(env, log);
  const sources = signal([]);
  const showsConfig = signal(null);
  const initialRoute = getRouteFromUrl();
  trackPageView(window.location.pathname);

  const history = createHistoryStore({ storageKey: "vodcasts_history_v1" });
  const player = createPlayerService({ env, log, history });

  const mount = document.getElementById("app");
  if (!mount) throw new Error("Missing #app");

  render(
    html`<${App}
      env=${env}
      log=${log}
      sources=${sources}
      showsConfig=${showsConfig}
      player=${player}
      history=${history}
    />`,
    mount
  );

  try {
    log.info("Loading sources…");
    const loaded = await loadSources(env);
    sources.value = loaded;
    log.info(`Sources loaded: ${loaded.length}`);
    player.setSources(loaded, { initialRoute });

    if (env.showsConfigUrl) {
      try {
        const res = await fetch(env.showsConfigUrl);
        if (res.ok) {
          const data = await res.json();
          showsConfig.value = data;
        }
      } catch (e) {
        log.error("Failed to load shows config: " + String(e?.message || e));
      }
    }
  } catch (err) {
    log.error(String(err?.message || err || "sources load failed"));
    throw err;
  }
}
