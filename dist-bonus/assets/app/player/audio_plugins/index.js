/**
 * Audio-only display plugins registry.
 * Each plugin: (container, { media, episode, source }) => { start, destroy }
 * Optional: settings(player) => html for plugin-specific settings.
 */

import { wave, waveSettings } from "./wave.js";
import { starfield, starfieldSettings } from "./starfield.js";
import { clock, clockSettings } from "./clock.js";
import { weather, weatherSettings } from "./weather.js";
import { aquarium, aquariumSettings } from "./aquarium.js";
import { cross, crossSettings } from "./cross.js";
import { americana, americanaSettings } from "./americana.js";
import { slideshow, slideshowSettings } from "./slideshow.js";
import { fireworks, fireworksSettings } from "./fireworks.js";

export const AUDIO_DISPLAY_PLUGINS = {
  wave: { fn: wave, label: "Wave", settings: waveSettings },
  starfield: { fn: starfield, label: "Starfield", settings: starfieldSettings },
  clock: { fn: clock, label: "Clock", settings: clockSettings },
  weather: { fn: weather, label: "Weather", settings: weatherSettings },
  aquarium: { fn: aquarium, label: "Aquarium", settings: aquariumSettings },
  cross: { fn: cross, label: "Stained Glass", settings: crossSettings },
  americana: { fn: americana, label: "Americana", settings: americanaSettings },
  slideshow: { fn: slideshow, label: "Slideshow", settings: slideshowSettings },
  fireworks: { fn: fireworks, label: "Fireworks", settings: fireworksSettings },
};

const PLUGIN_IDS = Object.keys(AUDIO_DISPLAY_PLUGINS);

export function getNextPluginId(currentId) {
  const i = PLUGIN_IDS.indexOf(currentId);
  return PLUGIN_IDS[(i + 1) % PLUGIN_IDS.length] || "wave";
}

const STORAGE_KEY = "vodcasts_audio_display_v1";

export function getPreferredPlugin() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v && AUDIO_DISPLAY_PLUGINS[v]) return v;
  } catch {}
  return "wave";
}

export function setPreferredPlugin(id) {
  try {
    if (AUDIO_DISPLAY_PLUGINS[id]) {
      localStorage.setItem(STORAGE_KEY, id);
      return true;
    }
  } catch {}
  return false;
}

export function createPlugin(id, container, opts) {
  const p = AUDIO_DISPLAY_PLUGINS[id];
  if (!p) return null;
  try {
    return p.fn(container, opts);
  } catch (e) {
    console.warn("[vodcasts] Audio plugin failed:", id, e);
    return null;
  }
}
