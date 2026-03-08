from __future__ import annotations

import argparse
import json
import os

from answer_engine_lib import answer_question, load_segment_context, parse_common_args, resolve_paths, search_segments


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Query the answer-engine transcript index.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="Search for matching segments/episodes.")
    parse_common_args(p_search)
    p_search.add_argument("--q", required=True, help="Free-text query/question.")
    p_search.add_argument("--limit", type=int, default=12, help="Max segments to return (default: 12).")
    p_search.add_argument("--candidates", type=int, default=160, help="Initial FTS candidates to rerank (default: 160).")
    p_search.add_argument("--include-noncontent", action="store_true", help="Allow intro/ad/outro segments to rank normally.")
    p_search.add_argument("--json", action="store_true", help="Emit JSON (default is a compact human-readable format).")

    p_answer = sub.add_parser("answer", help="Produce grounded timestamped answers for a full-text question.")
    parse_common_args(p_answer)
    p_answer.add_argument("--q", required=True, help="Free-text question, e.g. a reddit post title/body.")
    p_answer.add_argument("--answers", type=int, default=3, help="Max episode answers to return (default: 3).")
    p_answer.add_argument("--per-query-limit", type=int, default=8, help="Segments to keep per retrieval query (default: 8).")
    p_answer.add_argument("--candidates", type=int, default=180, help="FTS candidates per retrieval query (default: 180).")
    p_answer.add_argument("--review-candidates", type=int, default=6, help="LLM-reviewed candidate windows (default: 6).")
    p_answer.add_argument("--llm-url", default="", help="Optional local LLM endpoint, e.g. http://127.0.0.1:8765.")
    p_answer.add_argument("--include-noncontent", action="store_true", help="Allow intro/ad/outro segments to survive retrieval more easily.")
    p_answer.add_argument("--json", action="store_true", help="Emit JSON.")

    p_ctx = sub.add_parser("context", help="Show nearby segments for a specific segment id.")
    parse_common_args(p_ctx)
    p_ctx.add_argument("--id", type=int, required=True, help="segment_id from search results.")
    p_ctx.add_argument("--before", type=int, default=1, help="Segments before (default: 1).")
    p_ctx.add_argument("--after", type=int, default=1, help="Segments after (default: 1).")
    p_ctx.add_argument("--json", action="store_true", help="Emit JSON.")

    return p.parse_args()


def _print_search_text(payload: dict) -> None:
    if payload.get("error"):
        print(f'Error: {payload.get("error")}')
        return
    eps = payload.get("episodes") or []
    segs = payload.get("results") or []
    print(f'Query: {payload.get("query")}')
    print(f'FTS:   {payload.get("fts")}\n')

    if eps:
        print("Top episodes:")
        for i, e in enumerate(eps[:10], 1):
            print(f'  {i:>2}. {e.get("episode_title")}  [{e.get("feed")}]  score={e.get("score"):.3f}  {e.get("share_path")}')
        print()

    if segs:
        print("Top segments:")
        for i, s in enumerate(segs, 1):
            k = s.get("kind")
            kc = float(s.get("kind_conf") or 0.0)
            print(
                f'  {i:>2}. id={s.get("segment_id")} score={s.get("score"):.3f} '
                f'[{s.get("feed")}] {s.get("episode_title")} @ {int(s.get("start_sec") or 0)}s '
                f'kind={k}({kc:.2f})  {s.get("share_path")}'
            )
            print(f'      {s.get("snippet")}')
    else:
        print("No matches.")


def _print_context_text(payload: dict) -> None:
    if payload.get("error"):
        print(f'Error: {payload.get("error")}')
        return
    print(f'[{payload.get("feed")}] {payload.get("episode_title")}  ({payload.get("episode_slug")})')
    print(f'Share: {payload.get("share_path")}')
    print(f'Transcript: {payload.get("transcript_path")}\n')
    for c in payload.get("context") or []:
        print(f'  id={c.get("segment_id")} @ {int(c.get("start_sec") or 0)}s  kind={c.get("kind")}({float(c.get("kind_conf") or 0):.2f})')
        print(f'    {c.get("snippet")}')


def _print_answer_text(payload: dict) -> None:
    if payload.get("error"):
        print(f'Error: {payload.get("error")}')
        return
    plan = payload.get("plan") or {}
    answers = payload.get("answers") or []
    print(f'Question: {payload.get("query")}')
    if plan.get("intent"):
        print(f'Intent:   {plan.get("intent")}')
    if plan.get("search_queries"):
        print("Queries:")
        for q in plan.get("search_queries") or []:
            print(f"  - {q}")
    if plan.get("related_topics"):
        print("Topics:")
        for t in plan.get("related_topics") or []:
            print(f"  - {t}")
    print()

    if not answers:
        print("No grounded answers found.")
        return

    for i, ans in enumerate(answers, 1):
        print(f'{i}. {ans.get("episode_title")}  [{ans.get("feed")}]')
        print(f'   Watch: {ans.get("share_path")}  @ {ans.get("timecode")}')
        if ans.get("chapter") and isinstance(ans.get("chapter"), dict):
            ch = ans.get("chapter") or {}
            title = str(ch.get("title") or "").strip()
            kind = str(ch.get("kind") or "").strip()
            if title or kind:
                print(f'   Chapter: {kind + " - " if kind and title else kind}{title if title else ""}')
        if ans.get("recommendation"):
            print(f'   Recommendation: {ans.get("recommendation")}')
        elif ans.get("summary"):
            print(f'   Recommendation: {ans.get("summary")}')
        if ans.get("quote"):
            print(f'   Quote: "{ans.get("quote")}"')
        if ans.get("tags"):
            print(f'   Tags: {", ".join(ans.get("tags") or [])}')
        print()


def main() -> None:
    args = _parse_args()
    cache_dir, _transcripts_root, db_path = resolve_paths(args)
    transcripts_root = _transcripts_root
    _ = cache_dir  # reserved for future outputs / path printing

    if args.cmd == "search":
        payload = search_segments(
            db_path=db_path,
            q=str(args.q),
            limit=int(args.limit),
            candidates=int(args.candidates),
            include_noncontent=bool(args.include_noncontent),
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_search_text(payload)
        return

    if args.cmd == "answer":
        if str(args.llm_url or "").strip():
            os.environ["VOD_ANSWER_LLM_URL"] = str(args.llm_url).strip()
        payload = answer_question(
            db_path=db_path,
            transcripts_root=transcripts_root,
            q=str(args.q),
            answers=int(args.answers),
            per_query_limit=int(args.per_query_limit),
            candidates=int(args.candidates),
            review_candidates=int(args.review_candidates),
            include_noncontent=bool(args.include_noncontent),
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_answer_text(payload)
        return

    if args.cmd == "context":
        payload = load_segment_context(db_path=db_path, segment_id=int(args.id), before=int(args.before), after=int(args.after))
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_context_text(payload)
        return

    raise SystemExit(2)


if __name__ == "__main__":
    main()
