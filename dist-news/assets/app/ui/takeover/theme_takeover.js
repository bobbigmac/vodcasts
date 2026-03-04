import { html } from "../../runtime/vendor.js";

export function ThemeTakeover({ theme, setTheme, takeover }) {
  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Theme" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Theme</div>
      </div>
      <div class="guideBarTakeoverBody">
        <button
          class=${"guideBtn" + (theme === "modern" ? " active" : "")}
          title="Modern theme"
          onClick=${() => {
            setTheme("modern");
            takeover.close();
          }}
        >
          Modern
        </button>
        <button
          class=${"guideBtn" + (theme === "dos" ? " active" : "")}
          title="DOS theme"
          onClick=${() => {
            setTheme("dos");
            takeover.close();
          }}
        >
          DOS
        </button>
        <button
          class=${"guideBtn" + (theme === "y2k" ? " active" : "")}
          title="Y2K theme"
          onClick=${() => {
            setTheme("y2k");
            takeover.close();
          }}
        >
          Y2K
        </button>
      </div>
    </div>
  `;
}

