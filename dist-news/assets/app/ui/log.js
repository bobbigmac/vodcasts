import { html, useEffect, useRef } from "../runtime/vendor.js";

export function LogPanel({ log }) {
  const entries = log.entries.value;
  const outRef = useRef(null);

  useEffect(() => {
    const el = outRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  return html`
    <div class="detailsLog">
      <div class="detailsLogHeader">
        <span>Log</span>
        <button id="btnClearLog" class="guideBtn" onClick=${() => log.clear()}>Clear</button>
      </div>
      <div id="logOutput" class="logOutput" role="log" ref=${outRef}>
        ${entries.map(
          (e) => html`<div class=${`logEntry ${e.level}`}>[${e.ts}] ${e.msg}</div>`
        )}
      </div>
    </div>
  `;
}
