function stripDiacritics(s) {
  const t = String(s || "");
  try {
    return t.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  } catch {
    return t;
  }
}

export function normalizeForSearch(v) {
  const s = stripDiacritics(String(v ?? "")).toLowerCase();
  return s
    .replace(/[\u0000-\u001f\u007f-\u009f\u200b\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function splitQuery(q) {
  const s = normalizeForSearch(q);
  if (!s) return [];
  return s.split(" ").filter(Boolean).slice(0, 12);
}

export function matchesAllTokens(tokens, haystack) {
  if (!tokens?.length) return true;
  const h = String(haystack || "");
  for (const t of tokens) {
    if (!t) continue;
    if (!h.includes(t)) return false;
  }
  return true;
}

function fmtDurationTag(sec) {
  const s = Number(sec);
  if (!Number.isFinite(s) || s <= 0) return "";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.floor(s)}s`;
}

export function episodeSearchHaystack(source, ep) {
  const mediaUrl = String(ep?.media?.url || "");
  const mediaType = String(ep?.media?.type || "");
  const tags = [];
  if ((ep?.transcripts || []).length) tags.push("cc");
  if (ep?.chaptersInline?.length || ep?.chaptersExternal?.url) tags.push("chapters");
  if (mediaUrl.toLowerCase().includes(".m3u8")) tags.push("hls");
  if (mediaUrl.toLowerCase().match(/\.(mp4|m4v|mov|webm)(\?|$)/)) tags.push("mp4");
  if (mediaType.toLowerCase().startsWith("video/")) tags.push("video");
  const durTag = fmtDurationTag(ep?.durationSec);
  if (durTag) tags.push(durTag);

  const parts = [
    source?.title,
    source?.id,
    source?.category,
    ep?.channelTitle,
    ep?.title,
    ep?.slug,
    ep?.dateText,
    ...tags,
  ];
  return normalizeForSearch(parts.filter(Boolean).join(" "));
}

