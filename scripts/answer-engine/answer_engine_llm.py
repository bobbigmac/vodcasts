from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import torch  # type: ignore
from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore


_DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
_COMMON_KINDS = {
    "start",
    "welcome",
    "intro",
    "worship",
    "prayer",
    "message",
    "teaching",
    "application",
    "topic",
    "scripture",
    "reading",
    "illustration",
    "story",
    "testimony",
    "conversation",
    "interview",
    "q_and_a",
    "response",
    "invitation",
    "communion",
    "announcements",
    "giving",
    "ad",
    "transition",
    "benediction",
    "outro",
}

_KIND_ALIASES = {
    "sermon": "teaching",
    "teaching_point": "teaching",
    "exposition": "teaching",
    "practical_application": "application",
    "application_point": "application",
    "storytelling": "story",
    "personal_story": "testimony",
    "discussion": "conversation",
    "qa": "q_and_a",
    "q&a": "q_and_a",
    "q_a": "q_and_a",
    "question_and_answer": "q_and_a",
    "altar_call": "invitation",
    "call_to_action": "invitation",
    "offering": "giving",
    "tithes": "giving",
    "closing_blessing": "benediction",
    "blessing": "benediction",
}


@dataclass(frozen=True)
class BoundaryDecision:
    keep: bool
    kind: str
    title: str
    tags: list[str]


@dataclass(frozen=True)
class ChapterMetadata:
    kind: str
    title: str
    tags: list[str]


def llm_chaptering_enabled() -> bool:
    raw = (os.environ.get("VOD_ANSWER_LLM") or "1").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def _model_name() -> str:
    return (os.environ.get("VOD_ANSWER_LLM_MODEL") or _DEFAULT_MODEL).strip()


def _device() -> str:
    forced = (os.environ.get("VOD_ANSWER_LLM_DEVICE") or "").strip()
    if forced:
        return forced
    return "cuda" if torch.cuda.is_available() else "cpu"


def _dtype() -> Any:
    device = _device()
    if device.startswith("cuda"):
        if hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float16
    return torch.float32


def _dtype_name() -> str:
    dt = _dtype()
    if dt is torch.bfloat16:
        return "bfloat16"
    if dt is torch.float16:
        return "float16"
    return "float32"


def _max_input_chars() -> int:
    try:
        return max(1000, int(os.environ.get("VOD_ANSWER_LLM_MAX_INPUT_CHARS") or "2400"))
    except Exception:
        return 2400


def _remote_url() -> str:
    return (os.environ.get("VOD_ANSWER_LLM_URL") or "").strip().rstrip("/")


def _server_mode() -> bool:
    raw = (os.environ.get("VOD_ANSWER_LLM_SERVER") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _use_remote() -> bool:
    return bool(_remote_url()) and not _server_mode()


def _http_timeout_sec() -> float:
    try:
        return max(5.0, float(os.environ.get("VOD_ANSWER_LLM_HTTP_TIMEOUT_SEC") or "180"))
    except Exception:
        return 180.0


def _clip_text(text: str, *, max_chars: int | None = None) -> str:
    s = " ".join(str(text or "").split()).strip()
    if not s:
        return ""
    limit = int(max_chars or _max_input_chars())
    if len(s) <= limit:
        return s
    head = s[: int(limit * 0.68)].rstrip()
    tail = s[-int(limit * 0.20) :].lstrip()
    return f"{head}\n...\n{tail}"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    s = str(text or "").strip()
    if not s:
        return None
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for idx in range(start, len(s)):
        ch = s[idx]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    raw = json.loads(s[start : idx + 1])
                except Exception:
                    return None
                return raw if isinstance(raw, dict) else None
    return None


def _normalize_kind(v: str, fallback: str) -> str:
    k = " ".join(str(v or "").strip().lower().replace("-", "_").split())
    k = k.replace(" ", "_")
    k = _KIND_ALIASES.get(k, k)
    if not k:
        return fallback
    if k in _COMMON_KINDS:
        return k
    k = re.sub(r"[^a-z0-9_]+", "_", k).strip("_")
    k = re.sub(r"_+", "_", k)
    if len(k) < 3 or len(k) > 32:
        return fallback
    if k in {"chapter", "section", "segment", "content", "other", "misc", "general", "unknown"}:
        return fallback
    return k


def _allowed_kinds_csv() -> str:
    return ", ".join(sorted(_COMMON_KINDS))


def _kind_prompt_examples() -> str:
    return (
        "Common examples: welcome, worship, prayer, scripture, teaching, application, story, testimony, "
        "conversation, interview, q_and_a, invitation, giving, benediction, news_update, devotional, "
        "conference_talk, kids_story, panel_discussion, ministry_update, health_segment, finance_segment."
    )


def _normalize_tags(v: Any) -> list[str]:
    vals = v if isinstance(v, list) else []
    out: list[str] = []
    seen: set[str] = set()
    for item in vals:
        tag = " ".join(str(item or "").strip().lower().split())
        tag = re.sub(r"[^a-z0-9 /:+&'-]+", "", tag).strip(" -")
        if len(tag) < 3:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag[:40])
        if len(out) >= 6:
            break
    return out


def _normalize_title(v: str, fallback: str) -> str:
    title = " ".join(str(v or "").strip().split())
    if not title:
        return fallback
    title = title.strip(" -:;,.")
    if not title:
        return fallback
    return title[:96].rstrip()


@lru_cache(maxsize=1)
def _tokenizer():
    return AutoTokenizer.from_pretrained(_model_name())


@lru_cache(maxsize=1)
def _model():
    name = _model_name()
    device = _device()
    dtype = _dtype()
    kwargs: dict[str, Any] = {
        "dtype": dtype,
        "low_cpu_mem_usage": True,
    }
    if device.startswith("cuda"):
        kwargs["attn_implementation"] = "sdpa"
    try:
        model = AutoModelForCausalLM.from_pretrained(name, **kwargs)
    except TypeError:
        kwargs.pop("attn_implementation", None)
        model = AutoModelForCausalLM.from_pretrained(name, **kwargs)
    except Exception as exc:
        raise RuntimeError(f"failed to load LLM model {name}: {exc}") from exc
    if device:
        model = model.to(device)
    model.eval()
    return model


def model_info() -> dict[str, Any]:
    return {
        "enabled": llm_chaptering_enabled(),
        "model": _model_name(),
        "device": _device(),
        "dtype": _dtype_name(),
        "remote_url": _remote_url(),
        "server_mode": _server_mode(),
        "model_loaded": bool(_model.cache_info().currsize),
        "tokenizer_loaded": bool(_tokenizer.cache_info().currsize),
    }


def warmup_model() -> dict[str, Any]:
    _tokenizer()
    _model()
    return model_info()


def _chat_json(*, system: str, user: str, max_new_tokens: int = 128) -> dict[str, Any] | None:
    tok = _tokenizer()
    model = _model()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok([prompt], return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    pad_token_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=int(max(48, max_new_tokens)),
            do_sample=False,
            use_cache=True,
            pad_token_id=pad_token_id,
        )
    gen = out[0][inputs["input_ids"].shape[1] :]
    text = tok.decode(gen, skip_special_tokens=True)
    return _extract_json_object(text)


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    url = f"{_remote_url()}{path}"
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=_http_timeout_sec()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerror.URLError as exc:
        raise RuntimeError(f"{url}: {exc}") from exc
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"{url}: invalid JSON response") from exc
    return body if isinstance(body, dict) else None


def _review_boundary_local(*, before_text: str, after_text: str, title_hint: str = "") -> BoundaryDecision | None:
    system = (
        "You are helping build accurate podcast chapters. "
        "Decide whether the AFTER excerpt starts a new listener-visible chapter. "
        "Prefer keeping boundaries for a clear new section a human would notice: teaching, application, scripture reading, story, testimony, conversation, response, worship, prayer, giving, announcements, benediction, or outro. "
        "Reject boundaries when the speaker is simply continuing the same argument. "
        "Return JSON only with keys keep, kind, title, tags. "
        f"Use one of these common kinds when they fit: {_allowed_kinds_csv()}. "
        f"{_kind_prompt_examples()} "
        "If none fit well, you may propose another short snake_case kind for a human-recognizable section."
    )
    user = (
        f"Title hint: {title_hint or '(none)'}\n\n"
        f"BEFORE:\n{_clip_text(before_text, max_chars=900)}\n\n"
        f"AFTER:\n{_clip_text(after_text, max_chars=1100)}\n\n"
        "Return compact JSON. "
        "Use a user-facing title of 4 to 10 words if keep=true. "
        "tags should be 2 to 5 topical phrases, lowercase, no filler words. "
        'Example: {"keep": true, "kind": "illustration", "title": "Why persistence matters", "tags": ["persistence", "prayer", "faith"]}'
    )
    try:
        raw = _chat_json(system=system, user=user, max_new_tokens=96)
    except Exception as exc:
        print(f"[answer-engine] LLM boundary review unavailable; falling back: {exc}", file=sys.stderr, flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    keep = bool(raw.get("keep"))
    kind = _normalize_kind(str(raw.get("kind") or ""), "topic")
    title = _normalize_title(str(raw.get("title") or ""), "")
    tags = _normalize_tags(raw.get("tags"))
    return BoundaryDecision(keep=keep, kind=kind, title=title, tags=tags)


def _refine_chapter_metadata_local(
    *,
    kind_hint: str,
    title_hint: str,
    chapter_text: str,
    prev_title: str = "",
    next_title: str = "",
) -> ChapterMetadata | None:
    system = (
        "You create chapter metadata for sermons and podcasts. "
        "Return JSON only with keys kind, title, tags. "
        f"Use one of these common kinds when they fit: {_allowed_kinds_csv()}. "
        f"{_kind_prompt_examples()} "
        "If another human-recognizable section label fits better, you may propose a short snake_case kind instead of forcing a generic one. "
        "Title should be concise, informative, and written for navigation. Avoid quoting filler or repeating generic prefixes unless the segment is actually prayer, ad, announcements, intro, transition, or outro. "
        "tags should be 2 to 6 topical phrases in lowercase."
    )
    user = (
        f"Current kind hint: {kind_hint}\n"
        f"Current title hint: {title_hint}\n"
        f"Previous chapter title: {prev_title or '(none)'}\n"
        f"Next chapter title: {next_title or '(none)'}\n\n"
        f"CHAPTER TEXT:\n{_clip_text(chapter_text)}\n\n"
        "Write a better user-visible title if the hint is weak. "
        "Prefer direct content labels like welcome, worship, scripture reading, teaching, practical application, story, testimony, conversation, prayer response, communion, giving, or closing blessing when appropriate. "
        'Return compact JSON like {"kind":"topic","title":"Serving others without fear","tags":["discipleship","service","mission"]}.'
    )
    try:
        raw = _chat_json(system=system, user=user, max_new_tokens=128)
    except Exception as exc:
        print(f"[answer-engine] LLM chapter refinement unavailable; falling back: {exc}", file=sys.stderr, flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    kind = _normalize_kind(str(raw.get("kind") or ""), kind_hint or "topic")
    title = _normalize_title(str(raw.get("title") or ""), title_hint)
    tags = _normalize_tags(raw.get("tags"))
    return ChapterMetadata(kind=kind, title=title, tags=tags)


def review_boundary(*, before_text: str, after_text: str, title_hint: str = "") -> BoundaryDecision | None:
    if not llm_chaptering_enabled():
        return None
    if _use_remote():
        try:
            raw = _post_json(
                "/review-boundary",
                {"before_text": before_text, "after_text": after_text, "title_hint": title_hint},
            )
            if isinstance(raw, dict):
                keep = bool(raw.get("keep"))
                kind = _normalize_kind(str(raw.get("kind") or ""), "topic")
                title = _normalize_title(str(raw.get("title") or ""), "")
                tags = _normalize_tags(raw.get("tags"))
                return BoundaryDecision(keep=keep, kind=kind, title=title, tags=tags)
        except Exception as exc:
            print(f"[answer-engine] LLM remote boundary review failed; falling back local: {exc}", file=sys.stderr, flush=True)
    return _review_boundary_local(before_text=before_text, after_text=after_text, title_hint=title_hint)


def refine_chapter_metadata(
    *,
    kind_hint: str,
    title_hint: str,
    chapter_text: str,
    prev_title: str = "",
    next_title: str = "",
) -> ChapterMetadata | None:
    if not llm_chaptering_enabled():
        return None
    if _use_remote():
        try:
            raw = _post_json(
                "/refine-chapter",
                {
                    "kind_hint": kind_hint,
                    "title_hint": title_hint,
                    "chapter_text": chapter_text,
                    "prev_title": prev_title,
                    "next_title": next_title,
                },
            )
            if isinstance(raw, dict):
                kind = _normalize_kind(str(raw.get("kind") or ""), kind_hint or "topic")
                title = _normalize_title(str(raw.get("title") or ""), title_hint)
                tags = _normalize_tags(raw.get("tags"))
                return ChapterMetadata(kind=kind, title=title, tags=tags)
        except Exception as exc:
            print(f"[answer-engine] LLM remote chapter refinement failed; falling back local: {exc}", file=sys.stderr, flush=True)
    return _refine_chapter_metadata_local(
        kind_hint=kind_hint,
        title_hint=title_hint,
        chapter_text=chapter_text,
        prev_title=prev_title,
        next_title=next_title,
    )
