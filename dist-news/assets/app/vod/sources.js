export async function loadSources(env) {
  const res = await fetch(env.sourcesUrl, { cache: "no-store" });
  if (!res.ok) throw new Error(`sources: ${res.status}`);
  const json = await res.json();
  const sources = Array.isArray(json?.sources) ? json.sources : [];
  return sources;
}

