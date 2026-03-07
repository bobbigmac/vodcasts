from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore
from keybert import KeyBERT  # type: ignore


@dataclass(frozen=True)
class TextSpan:
    start: float
    end: float
    text: str


def _model_name() -> str:
    # Small + fast; good enough for topic shifts.
    return (os.environ.get("VOD_ANSWER_EMBED_MODEL") or "sentence-transformers/all-MiniLM-L6-v2").strip()


def _model_device() -> str:
    return (os.environ.get("VOD_ANSWER_DEVICE") or "cuda").strip()


@lru_cache(maxsize=1)
def _model():
    device = _model_device()
    try:
        return SentenceTransformer(_model_name(), device=device)
    except Exception as exc:
        if device != "cpu":
            print(f"[answer-engine] semantic model init failed on {device}; retrying on cpu: {exc}", file=sys.stderr, flush=True)
            return SentenceTransformer(_model_name(), device="cpu")
        raise


@lru_cache(maxsize=1)
def _keybert():
    # Reuse the same embedding model for both topic shifts and title keyphrases.
    return KeyBERT(model=_model())


def _embed_texts(texts: Sequence[str]):
    # normalize_embeddings gives us cosine similarity via dot product.
    m = _model()
    return m.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)


def pick_chapter_times(
    spans: Iterable[TextSpan],
    *,
    total_sec: float,
    main_start_sec: float = 0.0,
    min_gap_sec: float = 6 * 60.0,
    max_chapters: int = 14,
) -> list[float]:
    """
    Lightweight semantic topic-shift detection:
    - embed per span
    - find low cosine-similarity transitions
    - enforce time spacing
    """
    items = [s for s in spans if (s.text or "").strip()]
    if len(items) < 8:
        return []

    # Keep spans inside the “content area” when available.
    if main_start_sec > 0.0:
        items2 = [s for s in items if float(s.end) >= float(main_start_sec)]
        if len(items2) >= 8:
            items = items2

    texts = []
    for s in items:
        t = " ".join(str(s.text or "").split())
        # Truncate: this is for topic shift, not detailed semantics.
        texts.append(t[:1200])

    emb = _embed_texts(texts)
    if len(emb) != len(items):
        return []

    # Similarity between consecutive spans (embeddings are already normalized).
    sims = np.sum(emb[:-1] * emb[1:], axis=1)
    sims = np.clip(sims, -1.0, 1.0)
    if sims.size < 6:
        return []

    # Lower similarity => stronger topic shift. Pick candidates below a robust threshold.
    q = float(np.quantile(sims, 0.22))
    mu = float(np.mean(sims))
    sig = float(np.std(sims)) or 1e-6
    thr = min(q, mu - 0.70 * sig)

    candidates: list[tuple[float, float]] = []
    for i, sim in enumerate(sims.tolist()):
        if float(sim) <= float(thr):
            t = float(items[i + 1].start)
            if t <= 0.0 or t >= float(total_sec) - 60.0:
                continue
            strength = float((thr - float(sim)) / max(1e-6, sig))
            candidates.append((t, strength))

    # Strongest first, then keep spaced out.
    candidates.sort(key=lambda x: x[1], reverse=True)
    out: list[float] = []
    for t, _strength in candidates:
        if main_start_sec > 0.0 and t < float(main_start_sec) + 60.0:
            continue
        if out and min(abs(t - x) for x in out) < float(min_gap_sec):
            continue
        out.append(t)
        if len(out) >= int(max_chapters):
            break

    out.sort()
    return out


def keyphrases_for_title(text: str, *, top_n: int = 6) -> list[str]:
    """
    Extract human-readable keyphrases for chapter titles using KeyBERT (MMR).
    Returns phrases ordered best-first.
    """
    s = " ".join(str(text or "").split()).strip()
    if len(s) < 40:
        return []
    m = _keybert()
    pairs = m.extract_keywords(
        s,
        keyphrase_ngram_range=(1, 3),
        stop_words="english",
        use_mmr=True,
        diversity=0.65,
        top_n=int(max(1, top_n)),
    )
    out: list[str] = []
    seen: set[str] = set()
    for kw, _score in pairs or []:
        k = " ".join(str(kw or "").split()).strip()
        if not k:
            continue
        c = k.lower()
        if c in seen:
            continue
        seen.add(c)
        out.append(k)
    return out


def _split_sentences(text: str) -> list[str]:
    s = " ".join(str(text or "").split()).strip()
    if not s:
        return []
    parts = re.split(r"(?<=[.!?])\s+", s)
    out: list[str] = []
    for part in parts:
        sent = " ".join(part.split()).strip()
        if not sent:
            continue
        if sum(1 for ch in sent if ch.isalpha()) < 16:
            continue
        out.append(sent)
    return out


def representative_sentence(text: str, *, max_chars: int = 110) -> str:
    """
    Pick the most central sentence for a chunk of transcript text.
    This avoids titles that are just keyword lists.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return ""
    if len(sentences) == 1:
        sent = sentences[0]
    else:
        emb = _embed_texts(sentences)
        centroid = np.mean(emb, axis=0)
        centroid_norm = float(np.linalg.norm(centroid)) or 1.0
        centroid = centroid / centroid_norm

        def score(idx: int) -> float:
            sent = sentences[idx]
            sim = float(np.dot(emb[idx], centroid))
            n = len(sent)
            if n < 36:
                sim -= 0.10
            elif n > 150:
                sim -= 0.08
            # Prefer the sentence to be a little way into the chunk, not a cold open.
            if idx == 0:
                sim -= 0.04
            return sim

        sent = sentences[max(range(len(sentences)), key=score)]

    sent = re.sub(r"^(and|but|so|well|now|therefore)\s+", "", sent, flags=re.I).strip()
    sent = re.sub(r"\s+", " ", sent).strip(" .,:;-")
    if len(sent) <= max_chars:
        return sent
    return sent[: max_chars - 1].rstrip() + "..."
