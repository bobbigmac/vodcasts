export async function loadChaptersForEpisode({ env, episode, fetchText }) {
  if (episode?.chaptersInline?.length) return episode.chaptersInline;
  const ext = episode?.chaptersExternal;
  if (!ext?.url) return [];
  const txt = await fetchText(ext.url, "auto", { useCache: false });
  const json = JSON.parse(txt);
  const chapters = Array.isArray(json?.chapters) ? json.chapters : [];
  return chapters
    .map((c) => ({ t: Number(c.startTime) || Number(c.start_time) || 0, name: String(c.title || c.name || "Chapter") }))
    .filter((c) => Number.isFinite(c.t));
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

