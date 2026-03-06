from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.shared import VODCASTS_ROOT, fetch_url, write_json
from scripts.sources import Source, load_sources_config


_PLAYABLE_TYPES = {"text/vtt", "application/x-subrip", "application/srt"}


@dataclass(frozen=True)
class TranscriptCandidate:
    url: str
    typ: str
    lang: str
    is_captions: bool
    is_playable: bool


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Cache provided transcripts (podcast:transcript) and optionally generate missing ones using WhisperX.\n"
            "Designed for local/offline processing (no build integration)."
        )
    )
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "dev.md"), help="Feeds config (.md or .json).")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "dev"), help="Cache directory.")
    p.add_argument(
        "--out",
        default="",
        help="Output directory for transcript cache (default: <cache>/transcripts).",
    )
    p.add_argument(
        "--tag",
        default="sermons",
        help="Only process sources that match this tag/category (default: sermons). Use --all-sources to ignore.",
    )
    p.add_argument("--all-sources", action="store_true", help="Process all sources (ignores --tag filter).")
    p.add_argument(
        "--max-episodes-per-feed",
        type=int,
        default=0,
        help="Limit episodes processed per feed (0 = all).",
    )
    p.add_argument(
        "--download-provided",
        action="store_true",
        help="Download provided podcast:transcript assets when present (default).",
    )
    p.add_argument(
        "--no-download-provided",
        dest="download_provided",
        action="store_false",
        help="Do not download provided transcripts (generation-only mode).",
    )
    p.set_defaults(download_provided=True)
    p.add_argument(
        "--generate-missing",
        action="store_true",
        help="Generate transcript/subtitles when none are available (or provided transcript is unusable).",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually write files / download / run ffmpeg+whisperx. Without this, prints a dry-run plan.",
    )
    p.add_argument("--refresh", action="store_true", help="Re-download/regenerate even if outputs already exist.")
    p.add_argument("--timeout-seconds", type=int, default=45, help="Per-download timeout (default: 45).")
    p.add_argument("--user-agent", default="vodcasts-transcripts/1.0", help="HTTP user-agent for downloads.")

    # WhisperX pipeline (only used when --generate-missing + --execute)
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable (default: ffmpeg).")
    p.add_argument("--whisperx", default="whisperx", help="whisperx executable (default: whisperx).")
    p.add_argument("--whisperx-model", default="large-v3", help="WhisperX model name (default: large-v3).")
    p.add_argument("--language", default="en", help="Language code for WhisperX (default: en).")
    p.add_argument(
        "--whisperx-extra-args",
        default="",
        help='Extra args appended to the whisperx command (e.g. "--compute_type int8 --batch_size 4").',
    )

    # Acceptance heuristics for provided transcripts
    p.add_argument("--min-text-chars", type=int, default=200, help="Minimum extracted text chars to accept (default: 200).")
    p.add_argument("--min-words", type=int, default=30, help="Minimum extracted word count to accept (default: 30).")
    return p.parse_args()


def _norm(s: str) -> str:
    return str(s or "").strip()


def _matches_tag(source: Source, tag: str) -> bool:
    t = _norm(tag).lower()
    if not t:
        return True
    if _norm(source.category).lower() == t:
        return True
    if t in _norm(source.category).lower():
        return True
    tags = tuple(_norm(x).lower() for x in (source.tags or ()))
    return t in tags


def _ext_for_type(typ: str) -> str:
    t = _norm(typ).lower()
    if t == "text/vtt":
        return "vtt"
    if t in ("application/x-subrip", "application/srt"):
        return "srt"
    if t.startswith("text/"):
        return "txt"
    return "bin"


_SRT_TS_RE = re.compile(r"^\\d{2}:\\d{2}:\\d{2}[,.]\\d{3}\\s+-->\\s+\\d{2}:\\d{2}:\\d{2}[,.]\\d{3}")
_VTT_TS_RE = re.compile(r"^\\d{2}:\\d{2}:\\d{2}\\.\\d{3}\\s+-->\\s+\\d{2}:\\d{2}:\\d{2}\\.\\d{3}")


def _extract_text_from_srt(s: str) -> str:
    out: list[str] = []
    for raw in (s or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if _SRT_TS_RE.match(line):
            continue
        # Drop common formatting tags
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        out.append(line)
    return " ".join(out).strip()


def _extract_text_from_vtt(s: str) -> str:
    out: list[str] = []
    for raw in (s or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if _VTT_TS_RE.match(line):
            continue
        if "-->" in line and (":" in line and "." in line):
            # tolerate non-standard timestamps
            continue
        if line.startswith("NOTE"):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        out.append(line)
    return " ".join(out).strip()


def _srt_to_vtt(srt: str) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for raw in (srt or "").splitlines():
        line = raw.rstrip("\n")
        if line.strip().isdigit():
            continue
        if _SRT_TS_RE.match(line.strip()):
            lines.append(line.replace(",", "."))
            continue
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def _looks_like_srt(text: str) -> bool:
    s = (text or "").lstrip()
    if not s:
        return False
    # Heuristic: has at least one timestamp line
    return any(_SRT_TS_RE.match(ln.strip()) for ln in s.splitlines()[:200])


def _looks_like_vtt(text: str) -> bool:
    s = (text or "").lstrip()
    if not s:
        return False
    if s.upper().startswith("WEBVTT"):
        return True
    return any(_VTT_TS_RE.match(ln.strip()) for ln in s.splitlines()[:200])


def _is_sensible_text(text: str, *, min_chars: int, min_words: int) -> bool:
    t = (text or "").strip()
    if len(t) < int(min_chars):
        return False
    words = [w for w in re.split(r"\\s+", t) if w]
    if len(words) < int(min_words):
        return False
    letters = sum(ch.isalpha() for ch in t)
    return letters >= max(20, int(0.2 * len(t)))


def _pick_best_transcript_candidate(ep: dict[str, Any]) -> TranscriptCandidate | None:
    raw = ep.get("transcriptsAll") or []
    cands: list[TranscriptCandidate] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        url = _norm(t.get("url") or "")
        typ = _norm(t.get("type") or "").lower()
        if not url or not typ:
            continue
        lang = _norm(t.get("lang") or "en") or "en"
        is_captions = bool(t.get("isCaptions"))
        is_playable = typ in _PLAYABLE_TYPES
        cands.append(TranscriptCandidate(url=url, typ=typ, lang=lang, is_captions=is_captions, is_playable=is_playable))

    if not cands:
        return None

    def score(c: TranscriptCandidate) -> tuple[int, int, int]:
        # Prefer playable, captions, English.
        return (1 if c.is_playable else 0, 1 if c.is_captions else 0, 1 if c.lang.lower().startswith("en") else 0)

    cands.sort(key=score, reverse=True)
    return cands[0]


def _run(cmd: list[str], *, execute: bool) -> None:
    pretty = " ".join(json.dumps(x) for x in cmd)
    print(f"[cmd] {pretty}")
    if not execute:
        return
    subprocess.run(cmd, check=True)


def _download_bytes(url: str, *, timeout_seconds: int, user_agent: str, execute: bool) -> bytes | None:
    if not execute:
        return None
    res = fetch_url(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
    if res.status < 200 or res.status >= 300 or not res.content:
        raise ValueError(f"download failed: http {res.status} ({res.url})")
    return res.content


def _write_text(path: Path, text: str, *, execute: bool) -> None:
    print(f"[write] {path}")
    if not execute:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, data: bytes, *, execute: bool) -> None:
    print(f"[write] {path} ({len(data)} bytes)")
    if not execute:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _generate_with_whisperx(
    *,
    media_url: str,
    ffmpeg_cmd: str,
    whisperx_cmd: str,
    whisperx_model: str,
    language: str,
    whisperx_extra_args: str,
    execute: bool,
) -> tuple[str, str]:
    """
    Returns (srt_text, vtt_text).
    """
    if not execute:
        # dry-run placeholder
        return "", ""

    with tempfile.TemporaryDirectory(prefix="vodcasts.whisperx.") as td:
        tmp = Path(td)
        wav_path = tmp / "audio.wav"
        out_dir = tmp / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        _run(
            [
                ffmpeg_cmd,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                media_url,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav_path),
            ],
            execute=True,
        )

        cmd = [whisperx_cmd, str(wav_path), "--model", whisperx_model, "--language", language, "--output_dir", str(out_dir)]
        extra = (whisperx_extra_args or "").strip()
        if extra:
            cmd += shlex.split(extra)
        _run(cmd, execute=True)

        # WhisperX typically writes <stem>.srt (and often json/txt) into output_dir.
        base = wav_path.stem
        srt_path = out_dir / f"{base}.srt"
        vtt_path = out_dir / f"{base}.vtt"
        if srt_path.exists():
            srt_text = srt_path.read_text(encoding="utf-8", errors="replace")
            return srt_text, _srt_to_vtt(srt_text)
        if vtt_path.exists():
            vtt_text = vtt_path.read_text(encoding="utf-8", errors="replace")
            # best-effort: also return an SRT-ish variant
            return "", vtt_text

        # Fallback: take any .srt produced.
        any_srt = next(iter(out_dir.glob("*.srt")), None)
        if any_srt and any_srt.exists():
            srt_text = any_srt.read_text(encoding="utf-8", errors="replace")
            return srt_text, _srt_to_vtt(srt_text)

        raise ValueError(f"whisperx produced no .srt/.vtt in {out_dir}")


def main() -> None:
    args = _parse_args()
    feeds_path = Path(args.feeds)
    cache_dir = Path(args.cache)
    feeds_cache_dir = cache_dir / "feeds"
    out_dir = Path(args.out) if args.out else (cache_dir / "transcripts")

    cfg = load_sources_config(feeds_path)
    sources = list(cfg.sources)

    tag = _norm(args.tag)
    if not args.all_sources and tag:
        sources = [s for s in sources if _matches_tag(s, tag)]

    # Prioritize sermon-tagged feeds first even when --all-sources is set.
    if args.all_sources and tag:
        sources.sort(key=lambda s: (not _matches_tag(s, tag), s.id))
    else:
        sources.sort(key=lambda s: s.id)

    print(f"[plan] feeds={feeds_path} cache={cache_dir} out={out_dir}")
    print(f"[plan] sources={len(sources)} (download_provided={bool(args.download_provided)} generate_missing={bool(args.generate_missing)} execute={bool(args.execute)})")

    index: list[dict[str, Any]] = []
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for src in sources:
        feed_path = feeds_cache_dir / f"{src.id}.xml"
        if not feed_path.exists():
            print(f"[skip] {src.id}: missing cached feed {feed_path}")
            continue

        xml_text = feed_path.read_text(encoding="utf-8", errors="replace")
        _features, channel_title, episodes, _image = parse_feed_for_manifest(xml_text, source_id=src.id, source_title=src.title)

        eps = list(episodes or [])
        if args.max_episodes_per_feed and int(args.max_episodes_per_feed) > 0:
            eps = eps[: int(args.max_episodes_per_feed)]

        feed_out = out_dir / src.id
        if args.execute:
            feed_out.mkdir(parents=True, exist_ok=True)
            write_json(feed_out / "_feed.meta.json", {"feed_slug": src.id, "feed_title": channel_title, "feed_url": src.feed_url, "generated_at": now_iso})

        for ep in eps:
            if not isinstance(ep, dict):
                continue
            ep_slug = _norm(ep.get("slug") or "")
            if not ep_slug:
                continue

            final_vtt = feed_out / f"{ep_slug}.vtt"
            final_txt = feed_out / f"{ep_slug}.txt"
            meta_path = feed_out / f"{ep_slug}.meta.json"

            if not args.refresh and (final_vtt.exists() or final_txt.exists()):
                continue

            ep_title = _norm(ep.get("title") or "")
            ep_date = _norm(ep.get("dateText") or "")
            media_url = _norm((ep.get("media") or {}).get("url") if isinstance(ep.get("media"), dict) else "")

            cand = _pick_best_transcript_candidate(ep)
            chosen = None
            provided_ok = False
            provided_bytes: bytes | None = None
            provided_ext = ""
            provided_text = ""
            provided_kind = ""

            if cand and args.download_provided:
                provided_ext = _ext_for_type(cand.typ)
                provided_path = feed_out / f"{ep_slug}.provided.{provided_ext}"
                print(f"[want] {src.id}/{ep_slug}: provided transcript ({cand.typ}, {cand.lang}) {cand.url}")
                try:
                    provided_bytes = _download_bytes(
                        cand.url, timeout_seconds=int(args.timeout_seconds), user_agent=str(args.user_agent), execute=bool(args.execute)
                    )
                    if provided_bytes is not None:
                        _write_bytes(provided_path, provided_bytes, execute=bool(args.execute))
                        text = provided_bytes.decode("utf-8", errors="replace")
                        if _looks_like_vtt(text) or cand.typ == "text/vtt":
                            provided_kind = "vtt"
                            provided_text = _extract_text_from_vtt(text)
                            if _is_sensible_text(provided_text, min_chars=int(args.min_text_chars), min_words=int(args.min_words)):
                                provided_ok = True
                                _write_text(final_vtt, text if text.lstrip().upper().startswith("WEBVTT") else ("WEBVTT\n\n" + text), execute=bool(args.execute))
                                _write_text(final_txt, provided_text + "\n", execute=bool(args.execute))
                                chosen = "provided"
                        elif _looks_like_srt(text) or cand.typ in ("application/x-subrip", "application/srt"):
                            provided_kind = "srt"
                            provided_text = _extract_text_from_srt(text)
                            if _is_sensible_text(provided_text, min_chars=int(args.min_text_chars), min_words=int(args.min_words)):
                                provided_ok = True
                                vtt = _srt_to_vtt(text)
                                _write_text(final_vtt, vtt, execute=bool(args.execute))
                                _write_text(final_txt, provided_text + "\n", execute=bool(args.execute))
                                chosen = "provided"
                        else:
                            provided_kind = "text"
                            provided_text = re.sub(r"\\s+", " ", text).strip()
                            if _is_sensible_text(provided_text, min_chars=int(args.min_text_chars), min_words=int(args.min_words)):
                                provided_ok = True
                                _write_text(final_txt, provided_text + "\n", execute=bool(args.execute))
                                chosen = "provided"
                except Exception as e:
                    print(f"[warn] {src.id}/{ep_slug}: provided transcript download/parse failed: {e}")

            if chosen != "provided":
                if not args.generate_missing:
                    print(f"[miss] {src.id}/{ep_slug}: no usable provided transcript (generation disabled)")
                elif not media_url:
                    print(f"[skip] {src.id}/{ep_slug}: missing media url (cannot generate)")
                else:
                    print(f"[gen] {src.id}/{ep_slug}: whisperx from media {media_url}")
                    try:
                        srt_text, vtt_text = _generate_with_whisperx(
                            media_url=media_url,
                            ffmpeg_cmd=str(args.ffmpeg),
                            whisperx_cmd=str(args.whisperx),
                            whisperx_model=str(args.whisperx_model),
                            language=str(args.language),
                            whisperx_extra_args=str(args.whisperx_extra_args),
                            execute=bool(args.execute),
                        )
                        if vtt_text:
                            _write_text(final_vtt, vtt_text, execute=bool(args.execute))
                            txt = _extract_text_from_vtt(vtt_text)
                            _write_text(final_txt, txt + "\n", execute=bool(args.execute))
                        elif srt_text:
                            _write_text(final_vtt, _srt_to_vtt(srt_text), execute=bool(args.execute))
                            _write_text(final_txt, _extract_text_from_srt(srt_text) + "\n", execute=bool(args.execute))
                        chosen = "generated"
                    except Exception as e:
                        print(f"[error] {src.id}/{ep_slug}: generation failed: {e}")
                        chosen = "error"

            meta = {
                "generated_at": now_iso,
                "feed_slug": src.id,
                "feed_title": channel_title,
                "episode_slug": ep_slug,
                "episode_title": ep_title,
                "episode_date": ep_date,
                "media_url": media_url,
                "provided_transcript": (
                    {
                        "url": cand.url,
                        "type": cand.typ,
                        "lang": cand.lang,
                        "is_captions": cand.is_captions,
                        "is_playable": cand.is_playable,
                        "usable": bool(provided_ok),
                        "kind_detected": provided_kind,
                    }
                    if cand
                    else None
                ),
                "chosen": chosen,
                "paths": {
                    "vtt": str(final_vtt),
                    "txt": str(final_txt),
                    "meta": str(meta_path),
                },
                "whisperx": (
                    {
                        "enabled": bool(args.generate_missing),
                        "cmd": str(args.whisperx),
                        "model": str(args.whisperx_model),
                        "language": str(args.language),
                        "extra_args": str(args.whisperx_extra_args or ""),
                    }
                    if args.generate_missing
                    else None
                ),
            }
            print(f"[meta] {src.id}/{ep_slug}: {chosen}")
            if args.execute:
                write_json(meta_path, meta)
            index.append(meta)

    if args.execute:
        write_json(out_dir / "_index.json", {"generated_at": now_iso, "count": len(index), "items": index})
    else:
        print(f"[dry-run] would write index to: {out_dir / '_index.json'}")


if __name__ == "__main__":
    main()
