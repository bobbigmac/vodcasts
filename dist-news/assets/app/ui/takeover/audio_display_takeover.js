import { html } from "../../runtime/vendor.js";
import { AUDIO_DISPLAY_PLUGINS, getPreferredPlugin } from "../../player/audio_viz.js";

/**
 * Viz settings takeover. Header: title + Done only (no viz selector).
 * Body: plugin-specific settings for the currently active viz.
 */
export function AudioDisplayTakeover({ player, takeover }) {
  const current = getPreferredPlugin();
  const plugin = AUDIO_DISPLAY_PLUGINS[current];
  const SettingsUI = plugin?.settings;

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Viz settings" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader guideBarTakeoverHeaderViz">
        <span class="guideBarTakeoverTitle">${plugin?.label || "Viz"} settings</span>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody guideBarTakeoverBodyViz">
        ${SettingsUI ? SettingsUI(player, takeover) : html`<p class="guideBarTakeoverEmpty">No settings for this viz.</p>`}
      </div>
    </div>
  `;
}
