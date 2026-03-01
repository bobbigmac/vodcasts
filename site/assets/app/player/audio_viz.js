/**
 * Audio-only display: uses preferred plugin from registry.
 * Plugins in audio_plugins/; preference via localStorage.
 */

import {
  AUDIO_DISPLAY_PLUGINS,
  createPlugin,
  getPreferredPlugin,
} from "./audio_plugins/index.js";

export function createAudioViz(media, container, opts = {}) {
  const custom = typeof window.__VODCASTS_AUDIO_VIS__ === "function" ? window.__VODCASTS_AUDIO_VIS__ : null;
  const episode = opts.episode || null;
  const source = opts.source || null;
  const fullOpts = { media, episode, source, ...opts };

  if (custom) {
    try {
      return custom(container, fullOpts);
    } catch (e) {
      console.warn("[vodcasts] Custom audio vis failed:", e);
    }
  }

  const id = getPreferredPlugin();
  const instance = createPlugin(id, container, fullOpts);
  if (instance) return instance;

  return createPlugin("wave", container, fullOpts);
}

export { AUDIO_DISPLAY_PLUGINS, getPreferredPlugin, getNextPluginId, setPreferredPlugin } from "./audio_plugins/index.js";
