#!/usr/bin/env python3
"""
recall_memory.py — Sphere DiskStation 냥피디 세션 기억 회상 도구
과거에 저장/압축/인계된 세션 아카이브(chatbot-data/sessions/*.json)를 검색하고 복원합니다.

사용법:
  python3 tools/recall_memory.py "다이소"
  python3 tools/recall_memory.py "사주" "1979"
  python3 tools/recall_memory.py --recent 5
  python3 tools/recall_memory.py --session 20260916-112030-0a6303
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "sessions"
if not SESSIONS_DIR.exists():
    SESSIONS_DIR = Path("/volume1/homes/me/services/chatbot-data/sessions")


def format_ts(ts: Any) -> str:
    if not ts:
        return ""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.datetime.fromtimestamp(ts)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(ts, str):
            return ts[:19].replace("T", " ")
    except Exception:
        pass
    return str(ts)


def load_session_meta(file_path: Path) -> Optional[dict]:
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data["_file"] = file_path.name
        data["_mtime"] = file_path.stat().st_mtime
        return data
    except Exception:
        return None


def search_sessions(
    queries: List[str],
    limit: int = 5,
    case_sensitive: bool = False
) -> List[dict]:
    if not SESSIONS_DIR.exists():
        return []

    clean_queries = [q.strip() if case_sensitive else q.strip().lower() for q in queries if q.strip()]
    if not clean_queries:
        return []

    results = []
    session_files = sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    for p in session_files:
        meta = load_session_meta(p)
        if not meta:
            continue

        sid = meta.get("id") or p.stem
        history = meta.get("history") or []
        summary = str(meta.get("handoff_summary") or "")

        # Skip trivial doctor probes
        if len(history) <= 2:
            sample = " ".join(str(h.get("text") or "") for h in history)
            if "[doctor-probe]" in sample:
                continue

        matches = []

        # Check handoff summary
        summary_norm = summary if case_sensitive else summary.lower()
        if any(q in summary_norm for q in clean_queries):
            matches.append({
                "type": "handoff_summary",
                "role": "system_summary",
                "text": summary.strip(),
                "ts": meta.get("updated_at") or meta.get("_mtime")
            })

        # Check history turns
        for idx, turn in enumerate(history):
            role = turn.get("role") or "unknown"
            text = str(turn.get("text") or "")
            query_val = str(turn.get("query") or "")
            comb = (query_val + " " + text)
            comb_norm = comb if case_sensitive else comb.lower()

            if any(q in comb_norm for q in clean_queries):
                snippet = text.strip()
                if len(snippet) > 400:
                    # Highlight around match
                    for q in clean_queries:
                        pos = comb_norm.find(q)
                        if pos >= 0:
                            start = max(0, pos - 100)
                            end = min(len(snippet), pos + 250)
                            snippet = ("..." if start > 0 else "") + snippet[start:end] + ("..." if end < len(snippet) else "")
                            break
                matches.append({
                    "type": "turn",
                    "turn_index": idx,
                    "role": role,
                    "query": query_val if role == "btw" else "",
                    "text": snippet,
                    "ts": turn.get("ts")
                })

        if matches:
            results.append({
                "session_id": sid,
                "mtime": meta.get("_mtime"),
                "date": format_ts(meta.get("updated_at") or meta.get("_mtime")),
                "model": meta.get("model"),
                "turns_count": len(history),
                "summary": summary,
                "matches": matches,
            })
            if len(results) >= limit:
                break

    return results


def list_recent_sessions(limit: int = 8) -> List[dict]:
    if not SESSIONS_DIR.exists():
        return []

    items = []
    session_files = sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in session_files:
        meta = load_session_meta(p)
        if not meta:
            continue
        history = meta.get("history") or []
        if len(history) <= 2:
            sample = " ".join(str(h.get("text") or "") for h in history)
            if "[doctor-probe]" in sample:
                continue

        sid = meta.get("id") or p.stem
        last_turn = history[-1] if history else {}
        first_user = next((h for h in history if h.get("role") == "user"), {})

        items.append({
            "session_id": sid,
            "date": format_ts(meta.get("updated_at") or meta.get("_mtime")),
            "model": meta.get("model"),
            "turns_count": len(history),
            "summary": meta.get("handoff_summary") or "",
            "first_prompt": str(first_user.get("text") or "")[:80],
            "last_message": str(last_turn.get("text") or "")[:80],
            "predecessor": meta.get("predecessor_session_id") or "",
            "successor": meta.get("successor_session_id") or "",
        })
        if len(items) >= limit:
            break
    return items


def inspect_session(session_id: str) -> Optional[dict]:
    target = SESSIONS_DIR / f"{session_id}.json"
    if not target.exists():
        candidates = list(SESSIONS_DIR.glob(f"*{session_id}*.json"))
        if candidates:
            target = candidates[0]
        else:
            return None
    meta = load_session_meta(target)
    return meta


def main():
    parser = argparse.ArgumentParser(description="Sphere DiskStation 냥피디 세션 기억 회상기")
    parser.add_argument("query", nargs="*", help="검색할 키워드 (여러 개 지정 가능)")
    parser.add_argument("--recent", type=int, nargs="?", const=5, help="최근 세션 목록 N건 조회")
    parser.add_argument("--session", type=str, help="특정 세션 ID 상세 조회")
    parser.add_argument("--limit", type=int, default=5, help="검색 결과 최대 건수 (기본 5)")
    parser.add_argument("--json", action="store_true", help="JSON 형태로 출력")
    args = parser.parse_args()

    if args.session:
        meta = inspect_session(args.session)
        if not meta:
            print(f"세션을 찾을 수 없습니다: {args.session}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(meta, ensure_ascii=False, indent=2))
            return

        sid = meta.get("id") or args.session
        print(f"✦ 세션 상세 조회: {sid}")
        print(f"• 갱신일: {format_ts(meta.get('updated_at') or meta.get('_mtime'))}")
        print(f"• 모델: {meta.get('model')}")
        if meta.get("predecessor_session_id"):
            print(f"• 이전 세션: {meta.get('predecessor_session_id')}")
        if meta.get("successor_session_id"):
            print(f"• 후속 세션: {meta.get('successor_session_id')}")
        if meta.get("handoff_summary"):
            print(f"\n[인계 요약 메모]\n{meta.get('handoff_summary')}")

        print("\n[대화 기록]")
        history = meta.get("history") or []
        for h in history:
            role = h.get("role")
            ts = format_ts(h.get("ts"))
            ts_str = f" ({ts})" if ts else ""
            if role == "btw":
                print(f"- [샛길 /btw]{ts_str} 질문: {h.get('query')}\n  답변: {str(h.get('text') or '').strip()}")
            else:
                prefix = "실장님" if role == "user" else ("냥피디" if role == "assistant" else role)
                print(f"- [{prefix}]{ts_str}: {str(h.get('text') or '').strip()}")
        return

    if args.recent is not None:
        items = list_recent_sessions(args.recent)
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return
        print(f"✦ 최근 세션 아카이브 ({len(items)}건)\n")
        for it in items:
            print(f"• [{it['date']}] 세션 {it['session_id']} (총 {it['turns_count']}턴)")
            if it.get("first_prompt"):
                print(f"  - 시작 질문: {it['first_prompt']}")
            if it.get("summary"):
                summary_oneline = it['summary'].replace('\n', ' ')
                if len(summary_oneline) > 100:
                    summary_oneline = summary_oneline[:97] + "..."
                print(f"  - 인계 요약: {summary_oneline}")
            if it.get("predecessor"):
                print(f"  - 이전 세션: {it['predecessor']}")
            if it.get("successor"):
                print(f"  - 후속 세션: {it['successor']}")
            print()
        return

    if args.query:
        results = search_sessions(args.query, limit=args.limit)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return

        query_str = " ".join(args.query)
        if not results:
            print(f"✦ 키워드 '{query_str}' 검색 결과가 없습니다냥.")
            return

        print(f"✦ 과거 세션 회상 결과: '{query_str}' ({len(results)}건 발견)\n")
        for res in results:
            print(f"==================================================")
            print(f"📁 세션: {res['session_id']} ({res['date']}) | 모델: {res['model']}")
            if res.get("summary"):
                print(f"[인계 요약]\n{res['summary'].strip()}\n")
            print(f"[매칭된 대화 발췌]")
            for m in res.get("matches", []):
                role_kr = "실장님" if m["role"] == "user" else ("냥피디" if m["role"] == "assistant" else m["role"])
                ts_str = f" ({format_ts(m['ts'])})" if m.get("ts") else ""
                if m.get("type") == "handoff_summary":
                    continue
                print(f"• [{role_kr}]{ts_str}:")
                for line in m["text"].splitlines():
                    print(f"    {line}")
            print()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
