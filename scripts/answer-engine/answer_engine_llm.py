from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import torch  # type: ignore
from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore


_DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOTENV_LOADED = False


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


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    search_queries: list[str]
    related_topics: list[str]


@dataclass(frozen=True)
class AnswerReview:
    relevant: bool
    relevance: float
    start_segment_id: int
    quote_segment_id: int
    summary: str
    why_relevant: str
    quote: str
    tags: list[str]


@dataclass(frozen=True)
class AnswerSummary:
    relevant: bool
    relevance: float
    recommendation: str
    summary: str
    why_relevant: str
    tags: list[str]


def _load_repo_env() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    for name in (".env", ".env.txt"):
        path = _REPO_ROOT / name
        if not path.exists():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = str(raw_line or "").strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key or key in os.environ:
                    continue
                val = value.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
                    val = val[1:-1]
                os.environ[key] = val
        except Exception:
            continue


_load_repo_env()


def llm_chaptering_enabled() -> bool:
    raw = (os.environ.get("VOD_ANSWER_LLM") or "1").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def _llm_provider() -> str:
    raw = (os.environ.get("VOD_ANSWER_LLM_PROVIDER") or "").strip().lower()
    if raw in {"openai", "local"}:
        return raw
    model = (os.environ.get("VOD_ANSWER_LLM_MODEL") or "").strip()
    if model.lower().startswith("openai:"):
        return "openai"
    return "local"


def _openai_api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _openai_model_name() -> str:
    raw = (os.environ.get("VOD_ANSWER_OPENAI_MODEL") or os.environ.get("OPENAI_MODEL") or "").strip()
    if raw:
        return raw
    model = (os.environ.get("VOD_ANSWER_LLM_MODEL") or "").strip()
    if model.lower().startswith("openai:"):
        return model.split(":", 1)[1].strip() or _OPENAI_DEFAULT_MODEL
    return _OPENAI_DEFAULT_MODEL


def _model_name() -> str:
    if _llm_provider() == "openai":
        return _openai_model_name()
    return (os.environ.get("VOD_ANSWER_LLM_MODEL") or _DEFAULT_MODEL).strip()


def _device() -> str:
    if _llm_provider() == "openai":
        return "api"
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
    if _llm_provider() == "openai":
        return "api"
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


def _normalize_text_line(v: str, fallback: str = "", *, max_len: int = 280) -> str:
    text = " ".join(str(v or "").strip().split())
    if not text:
        return fallback
    text = text.strip(" -:;,.")
    if not text:
        return fallback
    return text[:max_len].rstrip()


def _normalize_query_list(v: Any, fallback: list[str]) -> list[str]:
    vals = v if isinstance(v, list) else []
    out: list[str] = []
    seen: set[str] = set()
    for item in vals:
        q = _normalize_text_line(str(item or ""), "", max_len=120)
        if len(q) < 6:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= 8:
            break
    return out or fallback


def _normalize_unit_float(v: Any, default: float = 0.0) -> float:
    try:
        val = float(v)
    except Exception:
        return float(default)
    if val < 0.0:
        return 0.0
    if val > 1.0:
        return 1.0
    return val


def _normalize_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


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
    provider = _llm_provider()
    return {
        "enabled": llm_chaptering_enabled(),
        "provider": provider,
        "model": _model_name(),
        "device": _device(),
        "dtype": _dtype_name(),
        "remote_url": _remote_url(),
        "server_mode": _server_mode(),
        "model_loaded": provider == "local" and bool(_model.cache_info().currsize),
        "tokenizer_loaded": provider == "local" and bool(_tokenizer.cache_info().currsize),
    }


def warmup_model() -> dict[str, Any]:
    if _llm_provider() == "openai":
        return model_info()
    _tokenizer()
    _model()
    return model_info()


def _extract_openai_text(body: dict[str, Any]) -> str:
    txt = body.get("output_text")
    if isinstance(txt, str) and txt.strip():
        return txt.strip()
    parts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if str(content.get("type") or "") not in {"output_text", "text"}:
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _openai_chat_json(*, system: str, user: str, max_new_tokens: int = 128) -> dict[str, Any] | None:
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    payload = {
        "model": _model_name(),
        "instructions": system,
        "input": user,
        "max_output_tokens": int(max(48, max_new_tokens)),
        "store": False,
        "text": {"format": {"type": "json_object"}},
    }
    req = urlrequest.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=_http_timeout_sec()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise RuntimeError("OpenAI API returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise RuntimeError("OpenAI API returned an unexpected response type")
    err = body.get("error")
    if isinstance(err, dict) and err:
        raise RuntimeError(str(err.get("message") or "OpenAI API returned an error"))
    text = _extract_openai_text(body)
    return _extract_json_object(text)


def _chat_json(*, system: str, user: str, max_new_tokens: int = 128) -> dict[str, Any] | None:
    if _llm_provider() == "openai":
        return _openai_chat_json(system=system, user=user, max_new_tokens=max_new_tokens)
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


def _plan_query_local(*, question: str) -> QueryPlan | None:
    fallback_queries = [_normalize_text_line(question, "", max_len=120)] if str(question or "").strip() else []
    system = (
        "You expand user questions into grounded transcript-retrieval intents. "
        "Return JSON only with keys intent, search_queries, related_topics. "
        "search_queries should be 4 to 8 short search strings that cover different ways a speaker might discuss the issue. "
        "Do not just generate synonyms. Include adjacent ideas, emotional framing, practical framing, theological framing, and likely language a sermon or talk might use even without repeating the user's exact words. "
        "related_topics should be 3 to 8 concise lowercase topical phrases that identify the wider problem space, not just literal restatements."
    )
    user = (
        f"QUESTION:\n{_clip_text(question, max_chars=700)}\n\n"
        "Return compact JSON like "
        '{"intent":"seeking help with forgiveness after betrayal","search_queries":["forgiving someone who hurt you","betrayal and forgiveness","healing after broken trust"],"related_topics":["forgiveness","betrayal","trust","healing"]}'
    )
    try:
        raw = _chat_json(system=system, user=user, max_new_tokens=196)
    except Exception as exc:
        print(f"[answer-engine] LLM query planning unavailable: {exc}", file=sys.stderr, flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    intent = _normalize_text_line(str(raw.get("intent") or ""), fallback_queries[0] if fallback_queries else "", max_len=160)
    queries = _normalize_query_list(raw.get("search_queries"), fallback_queries)
    topics = _normalize_tags(raw.get("related_topics"))
    return QueryPlan(intent=intent, search_queries=queries, related_topics=topics)


def _review_answer_candidate_local(
    *,
    question: str,
    episode_title: str,
    chapter_hint: str,
    retrieval_queries: list[str],
    context_segments: list[dict[str, Any]],
) -> AnswerReview | None:
    seg_lines: list[str] = []
    for seg in context_segments[:8]:
        seg_id = _normalize_int(seg.get("segment_id"), 0)
        start_label = _normalize_text_line(str(seg.get("timecode") or ""), "", max_len=24)
        kind = _normalize_text_line(str(seg.get("kind") or ""), "", max_len=24)
        text = _normalize_text_line(str(seg.get("text") or ""), "", max_len=340)
        if seg_id <= 0 or not text:
            continue
        prefix = f"{seg_id}"
        if start_label:
            prefix += f" @ {start_label}"
        if kind:
            prefix += f" [{kind}]"
        seg_lines.append(f"- {prefix}: {text}")
    if not seg_lines:
        return None

    rq = ", ".join([_normalize_text_line(q, "", max_len=80) for q in retrieval_queries if _normalize_text_line(q, "", max_len=80)])
    system = (
        "You judge whether transcript excerpts materially answer a user's question. "
        "Return JSON only with keys relevant, relevance, start_segment_id, quote_segment_id, summary, why_relevant, quote, tags. "
        "Pick start_segment_id where the relevant discussion really begins. "
        "Pick quote_segment_id for the clearest literal line to quote. "
        "quote must be copied exactly from the chosen segment text. "
        "Mark relevant=true when the excerpts clearly address the user's concern directly or indirectly through explanation, theology, pastoral framing, practical counsel, or lived experience. "
        "Do not require a perfect one-sentence answer. "
        "If the speaker is clearly helping the listener understand or respond to the issue, that is relevant. "
        "Prefer the most specific segment that addresses the issue. "
        "Avoid choosing generic prayer, intro, setup, or broad transition lines when a later excerpt is more directly about the question. "
        "Choose quotes that actually express the relevant point, not surrounding filler. "
        "summary and why_relevant must be concrete and listener-facing, not keyword soup."
    )
    user = (
        f"QUESTION:\n{_clip_text(question, max_chars=600)}\n\n"
        f"EPISODE:\n{_normalize_text_line(episode_title, '', max_len=140)}\n\n"
        f"CHAPTER HINT:\n{_normalize_text_line(chapter_hint, '(none)', max_len=120)}\n\n"
        f"RETRIEVAL HINTS:\n{rq or '(none)'}\n\n"
        "CONTEXT SEGMENTS:\n"
        + "\n".join(seg_lines)
        + "\n\nReturn compact JSON like "
        '{"relevant":true,"relevance":0.84,"start_segment_id":123,"quote_segment_id":124,"summary":"The speaker explains ...","why_relevant":"This directly addresses ...","quote":"Forgiveness is not pretending it did not hurt.","tags":["forgiveness","betrayal","healing"]}'
    )
    try:
        raw = _chat_json(system=system, user=user, max_new_tokens=220)
    except Exception as exc:
        print(f"[answer-engine] LLM answer review unavailable: {exc}", file=sys.stderr, flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    return AnswerReview(
        relevant=bool(raw.get("relevant")),
        relevance=_normalize_unit_float(raw.get("relevance"), 0.0),
        start_segment_id=_normalize_int(raw.get("start_segment_id"), 0),
        quote_segment_id=_normalize_int(raw.get("quote_segment_id"), 0),
        summary=_normalize_text_line(str(raw.get("summary") or ""), "", max_len=220),
        why_relevant=_normalize_text_line(str(raw.get("why_relevant") or ""), "", max_len=260),
        quote=_normalize_text_line(str(raw.get("quote") or ""), "", max_len=220),
        tags=_normalize_tags(raw.get("tags")),
    )


def plan_query(*, question: str) -> QueryPlan | None:
    if not llm_chaptering_enabled():
        return None
    if _use_remote():
        try:
            raw = _post_json("/plan-query", {"question": question})
            if isinstance(raw, dict):
                fallback_queries = [_normalize_text_line(question, "", max_len=120)] if str(question or "").strip() else []
                return QueryPlan(
                    intent=_normalize_text_line(str(raw.get("intent") or ""), fallback_queries[0] if fallback_queries else "", max_len=160),
                    search_queries=_normalize_query_list(raw.get("search_queries"), fallback_queries),
                    related_topics=_normalize_tags(raw.get("related_topics")),
                )
        except Exception as exc:
            print(f"[answer-engine] LLM remote query planning failed; falling back local: {exc}", file=sys.stderr, flush=True)
    return _plan_query_local(question=question)


def review_answer_candidate(
    *,
    question: str,
    episode_title: str,
    chapter_hint: str,
    retrieval_queries: list[str],
    context_segments: list[dict[str, Any]],
) -> AnswerReview | None:
    if not llm_chaptering_enabled():
        return None
    if _use_remote():
        try:
            raw = _post_json(
                "/review-answer",
                {
                    "question": question,
                    "episode_title": episode_title,
                    "chapter_hint": chapter_hint,
                    "retrieval_queries": retrieval_queries,
                    "context_segments": context_segments,
                },
            )
            if isinstance(raw, dict):
                return AnswerReview(
                    relevant=bool(raw.get("relevant")),
                    relevance=_normalize_unit_float(raw.get("relevance"), 0.0),
                    start_segment_id=_normalize_int(raw.get("start_segment_id"), 0),
                    quote_segment_id=_normalize_int(raw.get("quote_segment_id"), 0),
                    summary=_normalize_text_line(str(raw.get("summary") or ""), "", max_len=220),
                    why_relevant=_normalize_text_line(str(raw.get("why_relevant") or ""), "", max_len=260),
                    quote=_normalize_text_line(str(raw.get("quote") or ""), "", max_len=220),
                    tags=_normalize_tags(raw.get("tags")),
                )
        except Exception as exc:
            print(f"[answer-engine] LLM remote answer review failed; falling back local: {exc}", file=sys.stderr, flush=True)
    return _review_answer_candidate_local(
        question=question,
        episode_title=episode_title,
        chapter_hint=chapter_hint,
        retrieval_queries=retrieval_queries,
        context_segments=context_segments,
    )


def _summarize_answer_candidate_local(
    *,
    question: str,
    episode_title: str,
    chapter_hint: str,
    retrieval_queries: list[str],
    context_segments: list[dict[str, Any]],
) -> AnswerSummary | None:
    seg_lines: list[str] = []
    for seg in context_segments[:5]:
        seg_id = _normalize_int(seg.get("segment_id"), 0)
        start_label = _normalize_text_line(str(seg.get("timecode") or ""), "", max_len=24)
        kind = _normalize_text_line(str(seg.get("kind") or ""), "", max_len=24)
        text = _normalize_text_line(str(seg.get("text") or ""), "", max_len=340)
        if seg_id <= 0 or not text:
            continue
        prefix = f"{seg_id}"
        if start_label:
            prefix += f" @ {start_label}"
        if kind:
            prefix += f" [{kind}]"
        seg_lines.append(f"- {prefix}: {text}")
    if not seg_lines:
        return None

    rq = ", ".join([_normalize_text_line(q, "", max_len=80) for q in retrieval_queries if _normalize_text_line(q, "", max_len=80)])
    system = (
        "You turn transcript excerpts into a grounded recommendation for someone asking for help. "
        "Return JSON only with keys relevant, relevance, recommendation, tags. "
        "Mark relevant=true when the speaker is clearly addressing the issue directly or indirectly through explanation, theology, pastoral framing, practical counsel, or lived experience. "
        "Do not invent quotes or timestamps. "
        "Write recommendation as natural, warm, concise advice in the style of a thoughtful friend replying to a Reddit or Facebook post. "
        "Speak directly to the person using 'you' when helpful. "
        "Summarize the advice or framing from the excerpt itself. "
        "Do not say 'the speaker says', 'this video', 'this episode', 'this clip', or 'this is relevant because'. "
        "Do not mention metadata, retrieval, or analysis. "
        "Keep it grounded in the provided excerpt."
    )
    user = (
        f"QUESTION:\n{_clip_text(question, max_chars=600)}\n\n"
        f"EPISODE:\n{_normalize_text_line(episode_title, '', max_len=140)}\n\n"
        f"CHAPTER HINT:\n{_normalize_text_line(chapter_hint, '(none)', max_len=120)}\n\n"
        f"RETRIEVAL HINTS:\n{rq or '(none)'}\n\n"
        "EXCERPTS:\n"
        + "\n".join(seg_lines)
        + "\n\nReturn compact JSON like "
        '{"relevant":true,"relevance":0.82,"recommendation":"If this is where you are, one helpful way to think about it is ... You do not have to force certainty overnight, but you can keep bringing it to God honestly.","tags":["forgiveness","betrayal","healing"]}'
    )
    try:
        raw = _chat_json(system=system, user=user, max_new_tokens=180)
    except Exception as exc:
        print(f"[answer-engine] LLM answer summary unavailable: {exc}", file=sys.stderr, flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    return AnswerSummary(
        relevant=bool(raw.get("relevant")),
        relevance=_normalize_unit_float(raw.get("relevance"), 0.0),
        recommendation=_normalize_text_line(str(raw.get("recommendation") or raw.get("summary") or ""), "", max_len=420),
        summary=_normalize_text_line(str(raw.get("recommendation") or raw.get("summary") or ""), "", max_len=420),
        why_relevant="",
        tags=_normalize_tags(raw.get("tags")),
    )


def summarize_answer_candidate(
    *,
    question: str,
    episode_title: str,
    chapter_hint: str,
    retrieval_queries: list[str],
    context_segments: list[dict[str, Any]],
) -> AnswerSummary | None:
    if not llm_chaptering_enabled():
        return None
    if _use_remote():
        try:
            raw = _post_json(
                "/summarize-answer",
                {
                    "question": question,
                    "episode_title": episode_title,
                    "chapter_hint": chapter_hint,
                    "retrieval_queries": retrieval_queries,
                    "context_segments": context_segments,
                },
            )
            if isinstance(raw, dict):
                return AnswerSummary(
                    relevant=bool(raw.get("relevant")),
                    relevance=_normalize_unit_float(raw.get("relevance"), 0.0),
                    recommendation=_normalize_text_line(str(raw.get("recommendation") or raw.get("summary") or ""), "", max_len=420),
                    summary=_normalize_text_line(str(raw.get("recommendation") or raw.get("summary") or ""), "", max_len=420),
                    why_relevant="",
                    tags=_normalize_tags(raw.get("tags")),
                )
        except Exception as exc:
            print(f"[answer-engine] LLM remote answer summary failed; falling back local: {exc}", file=sys.stderr, flush=True)
    return _summarize_answer_candidate_local(
        question=question,
        episode_title=episode_title,
        chapter_hint=chapter_hint,
        retrieval_queries=retrieval_queries,
        context_segments=context_segments,
    )
