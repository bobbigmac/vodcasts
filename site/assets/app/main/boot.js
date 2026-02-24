import { render, html, signal } from "../runtime/vendor.js";
import { getEnv } from "../runtime/env.js";
import { createLogger } from "../runtime/log.js";
import { loadSources } from "../vod/sources.js";
import { createHistoryStore } from "../state/history.js";
import { createPlayerService } from "../player/player.js";
import { App } from "./app.js";

export async function bootApp() {
  const env = getEnv();
  const log = createLogger();
  const sources = signal([]);

  const history = createHistoryStore({ storageKey: "vodcasts_history_v1" });
  const player = createPlayerService({ env, log, history });

  const mount = document.getElementById("app");
  if (!mount) throw new Error("Missing #app");

  render(html`<${App} env=${env} log=${log} sources=${sources} player=${player} history=${history} />`, mount);

  try {
    log.info("Loading sources…");
    const loaded = await loadSources(env);
    sources.value = loaded;
    log.info(`Sources loaded: ${loaded.length}`);
    player.setSources(loaded);
  } catch (err) {
    log.error(String(err?.message || err || "sources load failed"));
    throw err;
  }
}
