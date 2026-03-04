import { html } from "../runtime/vendor.js";

const DEFAULT_BOX = { x: 50, y: 78, w: 92, opacity: 1, scale: 1 };

export function SubtitleBox({ player }) {
  const box = player.subtitleBox.value || DEFAULT_BOX;
  const cue = player.subtitleCue.value;
  const showing = player.captions.value.showing;
  const available = player.captions.value.available;

  if (!available) return null;

  return html`
    <div class="subtitleBoxWrap">
      ${showing && cue?.text
        ? html`
            <div
              class="subtitleOverlayText"
              style=${{
                left: `${box.x ?? DEFAULT_BOX.x}%`,
                top: `${box.y ?? DEFAULT_BOX.y}%`,
                maxWidth: `${box.w ?? DEFAULT_BOX.w}%`,
                opacity: box.opacity ?? DEFAULT_BOX.opacity,
                "--sub-scale": box.scale ?? DEFAULT_BOX.scale,
              }}
            >
              ${cue.text}
            </div>
          `
        : ""}
    </div>
  `;
}
