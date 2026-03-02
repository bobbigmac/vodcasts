#!/usr/bin/env node
/**
 * Quick feed verification: exists, has items, has video (optional).
 * Timeout: 5s per feed. Fails fast.
 */
const TIMEOUT_MS = 5000;
const URLs = process.argv.slice(2).filter(Boolean);

async function verify(url) {
  try {
    const c = new AbortController();
    const t = setTimeout(() => c.abort(), TIMEOUT_MS);
    const res = await fetch(url, {
      headers: { "User-Agent": "vodcasts/verify", Accept: "application/xml, text/xml, */*" },
      signal: c.signal,
    });
    clearTimeout(t);
    if (!res.ok) return { ok: false, status: res.status };
    const xml = await res.text();
    const itemCount = (xml.match(/<item\b/g) || []).length + (xml.match(/<entry\b/g) || []).length;
    const hasVideo = /type\s*=\s*["']video\//i.test(xml) || /\.(mp4|m4v|mov|webm|m3u8)(\?|["'\s>])/i.test(xml);
    const title = xml.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim() || "";
    return { ok: true, itemCount, hasVideo, title };
  } catch (e) {
    return { ok: false, err: e?.message || "unknown" };
  }
}

async function main() {
  const results = [];
  for (const url of URLs) {
    const r = await verify(url);
    results.push({ url, ...r });
    process.stdout.write(r.ok ? "." : "x");
  }
  console.log("");
  console.log(JSON.stringify(results, null, 0));
}

main().catch(console.error);
