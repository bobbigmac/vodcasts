import { signal } from "./vendor.js";

export function createLogger({ max = 200 } = {}) {
  const entries = signal([]);

  function append(msg, level = "info") {
    const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const entry = { ts, msg: String(msg), level };
    const next = [...entries.value, entry];
    entries.value = next.length > max ? next.slice(next.length - max) : next;
  }

  return {
    entries,
    info: (m) => append(m, "info"),
    warn: (m) => append(m, "warn"),
    error: (m) => append(m, "error"),
    clear: () => {
      entries.value = [];
    },
  };
}
