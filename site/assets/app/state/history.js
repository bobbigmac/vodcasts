import { computed, signal } from "../runtime/vendor.js";

const SHORT_THRESHOLD_SEC = 30;

function videoKey(sourceId, episodeId) {
  return `${sourceId}::${episodeId}`;
}

export function createHistoryStore({ storageKey }) {
  const entries = signal([]);
  const current = signal(null);

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(storageKey) || "[]");
      entries.value = Array.isArray(raw) ? raw : [];
    } catch {
      entries.value = [];
    }
  }

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(entries.value));
    } catch {}
  }

  function startSegment({ sourceId, episodeId, episodeTitle, channelTitle, startTime }) {
    const cur = current.value;
    if (cur && videoKey(cur.sourceId, cur.episodeId) !== videoKey(sourceId, episodeId)) {
      entries.value = [{ ...cur }, ...entries.value];
      save();
    }
    current.value = {
      sourceId,
      episodeId,
      episodeTitle: episodeTitle || "",
      channelTitle: channelTitle || "",
      start: startTime ?? 0,
      end: startTime ?? 0,
      dur: NaN,
      at: Date.now(),
    };
  }

  function updateEnd(time, duration) {
    const cur = current.value;
    if (!cur || !Number.isFinite(time)) return;
    const end = Math.max(cur.start, time);
    const dur = Number.isFinite(duration) && duration > 0 ? duration : cur.dur;
    current.value = { ...cur, end, dur };
  }

  function markCurrentHadSleep() {
    const cur = current.value;
    if (!cur) return;
    current.value = { ...cur, hadSleep: true };
  }

  function finalize() {
    const cur = current.value;
    if (!cur) return;
    entries.value = [{ ...cur }, ...entries.value];
    save();
    current.value = null;
  }

  function clear() {
    entries.value = [];
    save();
  }

  function clearShort(thresholdSec = SHORT_THRESHOLD_SEC) {
    entries.value = entries.value.filter((e) => (e.end || 0) - (e.start || 0) >= thresholdSec);
    save();
  }

  function combine() {
    if (entries.value.length < 2) return;
    const out = [];
    let run = null;
    for (const e of entries.value) {
      const key = videoKey(e.sourceId, e.episodeId);
      if (run && videoKey(run.sourceId, run.episodeId) === key) {
        run.start = Math.min(run.start, e.start);
        run.end = Math.max(run.end, e.end);
        const a = Number(run.dur);
        const b = Number(e.dur);
        if (Number.isFinite(b) && b > 0) run.dur = Number.isFinite(a) && a > 0 ? Math.max(a, b) : b;
        if (e.hadSleep) run.hadSleep = true;
      } else {
        run = { ...e };
        out.push(run);
      }
    }
    entries.value = out;
    save();
  }

  const all = computed(() => {
    const cur = current.value;
    return cur ? [cur, ...entries.value] : entries.value;
  });

  load();

  return {
    entries,
    current,
    all,
    startSegment,
    updateEnd,
    markCurrentHadSleep,
    finalize,
    clear,
    clearShort,
    combine,
  };
}
