import { html } from "../../runtime/vendor.js";

const PREF_KEY = "vodcasts_sleep_times_v1";

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

function normalizeTimes(list) {
  const src = Array.isArray(list) ? list : [];
  const out = [];
  const seen = new Set();
  for (const n0 of src) {
    const n = Math.round(Number(n0));
    if (!Number.isFinite(n)) continue;
    const mins = clamp(n, 1, 240);
    if (seen.has(mins)) continue;
    seen.add(mins);
    out.push(mins);
  }
  out.sort((a, b) => a - b);
  return out.length ? out : [5, 15, 30, 60];
}

function getTimes() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREF_KEY) || "null");
    return normalizeTimes(raw);
  } catch {
    return [5, 15, 30, 60];
  }
}

function setTimes(next) {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(normalizeTimes(next)));
  } catch {}
}

function fmtMins(mins) {
  const m = Math.round(Number(mins) || 0);
  if (m === 60) return "1 hr";
  if (m === 90) return "1.5 hr";
  if (m === 120) return "2 hr";
  if (m % 60 === 0 && m >= 60) return `${m / 60} hr`;
  return `${m} min`;
}

export function SleepTakeover({ player, takeover }) {
  const sleep = player.sleep.value;
  const opts = getTimes();

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Sleep timer" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Sleep</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody">
        ${sleep.active ? html`<div class="takeoverHint">Remaining: ${sleep.label || "—"}</div>` : ""}
        <div class="takeoverOpts">
          ${opts.map(
            (mins) => html`
              <button
                class="guideBtn"
                title=${`Sleep ${mins} min`}
                onClick=${() => {
                  player.setSleepTimerMins(mins);
                  takeover.close();
                }}
              >
                ${fmtMins(mins)}
              </button>
            `
          )}
          ${sleep.active
            ? html`
                <button
                  class="guideBtn"
                  title="Cancel sleep timer"
                  onClick=${() => {
                    player.clearSleepTimer();
                    takeover.close();
                  }}
                >
                  Cancel
                </button>
              `
            : ""}
        </div>
      </div>
    </div>
  `;
}

export function SleepSettingsTakeover({ takeover }) {
  const selected = getTimes();
  const preset = [1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180];

  const toggle = (mins) => {
    const m = clamp(Math.round(Number(mins) || 0), 1, 240);
    const set = new Set(selected);
    if (set.has(m)) set.delete(m);
    else set.add(m);
    const next = normalizeTimes([...set]);
    setTimes(next);
    takeover.bump();
  };

  const reset = () => {
    setTimes([5, 15, 30, 60]);
    takeover.bump();
  };

  const timesNow = getTimes();

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Sleep settings" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Sleep settings</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverHint">Choose which countdown buttons appear in the Sleep menu.</div>
        <div class="takeoverGrid" title="Available sleep times">
          ${preset.map((m) => {
            const on = timesNow.includes(m);
            return html`
              <button class=${"guideBtn" + (on ? " active" : "")} title=${on ? `Remove ${fmtMins(m)}` : `Add ${fmtMins(m)}`} onClick=${() => toggle(m)}>
                ${fmtMins(m)}
              </button>
            `;
          })}
        </div>
        <div class="takeoverOpts">
          <button class="guideBtn" title="Reset to default times" onClick=${reset}>Reset</button>
        </div>
      </div>
    </div>
  `;
}
