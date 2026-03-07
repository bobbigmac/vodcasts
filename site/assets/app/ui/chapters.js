export async function loadChaptersForEpisode({ env, episode, fetchText }) {
  if (episode?.chaptersInline?.length) return episode.chaptersInline;
  const ext = episode?.chaptersExternal;
  const strictUrl = ext?.url ? String(ext.url) : "";

  function deriveAutoChapterUrls(ep) {
    const list = ep?.transcripts || [];
    const t = list.find((x) => String(x?.type || "").includes("vtt") || String(x?.type || "").includes("subrip")) || list[0] || null;
    const url0 = String(t?.url || "");
    if (!url0) return [];
    if (/^https?:\/\//i.test(url0)) return [];
    const url = url0.split("#")[0].split("?")[0];
    if (!/\.(vtt|srt)$/i.test(url)) return [];
    const stem = url.replace(/\.(vtt|srt)$/i, "");
    const out = [`${stem}.chapters.json`, `${stem}.chapters.auto.json`];

    // Also try the shared chapters cache folder:
    //   assets/transcripts/<feed>/<episode>.vtt -> assets/chapters/<feed>/<episode>.chapters.json
    const m = url.match(/^(.*?)(assets\\/transcripts\\/)([^/]+)\\/([^/]+)$/i);
    if (m) {
      const prefix = m[1] || "";
      const feed = m[3] || "";
      const file = m[4] || "";
      const base = file.replace(/\\.(vtt|srt)$/i, "");
      if (feed && base) out.unshift(`${prefix}assets/chapters/${feed}/${base}.chapters.json`);
    }

    return out;
  }

  const candidates = strictUrl ? [strictUrl] : deriveAutoChapterUrls(episode);
  if (!candidates.length) return [];

  const tryLoad = async (u) => {
    const txt = await fetchText(u, "auto", { useCache: false });
    const json = JSON.parse(txt);
    const chapters = Array.isArray(json?.chapters) ? json.chapters : [];
    return chapters
      .map((c) => ({ t: Number(c.startTime) || Number(c.start_time) || 0, name: String(c.title || c.name || "Chapter") }))
      .filter((c) => Number.isFinite(c.t));
  };

  let lastErr = null;
  for (const u of candidates) {
    try {
      return await tryLoad(u);
    } catch (e) {
      lastErr = e;
      // If we're only doing auto-chapters discovery, failing should be silent.
      if (!strictUrl) continue;
      throw e;
    }
  }
  if (strictUrl && lastErr) throw lastErr;
  return [];
}

export function renderChapters(container, chapters, { fmtTime, onJump }) {
  if (!container) return;
  container.innerHTML = "";
  for (const ch of chapters || []) {
    const row = document.createElement("div");
    row.className = "ch";

    const name = document.createElement("div");
    name.className = "chName";
    name.textContent = ch.name || "Chapter";

    const time = document.createElement("div");
    time.className = "chTime";
    time.textContent = fmtTime(ch.t);

    row.append(name, time);
    row.addEventListener("click", () => onJump?.(ch.t));
    container.appendChild(row);
  }
}
