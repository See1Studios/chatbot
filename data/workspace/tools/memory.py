#!/usr/bin/env python3
"""냥피디 장기 기억 — 명령줄.

규칙(형식·4KB 상한·락·백업·삭제 확인)은 코어 `memory_store.py`에 있고, 이 파일은 그것을 부르는 껍데기다.
셸이 없는 프로바이더는 MCP `memory` 도구로 같은 코어를 쓴다. 세션 아카이브 검색은 recall_memory.py.

  python3 tools/memory.py show
  python3 tools/memory.py add "실장님은 상대경로를 선호한다"
  python3 tools/memory.py add "open-higgsfield 기본 포트 3014" --section "운영 결정"
  python3 tools/memory.py search "포트"
  python3 tools/memory.py forget "open-higgsfield"        # 여러 줄이 맞으면 거절. 전부 지우려면 --all
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
MEM_DIR = WORKSPACE / "memory"


def _core():
    # workspace = <service root>/data/workspace unless the host says where the service root is
    root = os.environ.get("AGY_CHAT_ROOT") or str(WORKSPACE.parent.parent)
    sys.path.insert(0, root)
    try:
        import memory_store
    except ImportError as e:
        print("코어 모듈 memory_store.py를 불러오지 못했습니다 (%s). 실장님께 알려 주세요." % e, file=sys.stderr)
        raise SystemExit(1)
    return memory_store


def main() -> int:
    p = argparse.ArgumentParser(description="냥피디 장기 기억")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="MEMORY.md 전체 출력")
    pa = sub.add_parser("add", help="사실 한 줄 추가")
    pa.add_argument("text", nargs="+", help="기억할 사실")
    pa.add_argument("--section", default="", help="MEMORY.md의 ## 제목 중 하나 (기본: 첫 번째)")
    ps = sub.add_parser("search", help="부분 문자열 검색")
    ps.add_argument("text", nargs="+")
    pf = sub.add_parser("forget", help="부분 문자열이 들어간 줄 삭제")
    pf.add_argument("text", nargs="+")
    pf.add_argument("--all", action="store_true", help="여러 줄이 맞아도 전부 지운다")
    args = p.parse_args()

    ms = _core()
    try:
        if args.cmd == "show":
            sys.stdout.write(ms.read(MEM_DIR))
        elif args.cmd == "add":
            status, section, line = ms.add(MEM_DIR, " ".join(args.text), args.section or None)
            if status == "duplicate":
                print("이미 있는 사실에 가깝습니다. 추가하지 않았습니다.")
            else:
                print("기록함 → ## %s" % section)
            print(line)
        elif args.cmd == "search":
            q = " ".join(args.text).strip().lower()
            hits = ms.search(MEM_DIR, q)
            if not hits:
                print("'%s' 없음." % q)
            for section, line in hits:
                print("[%s] %s" % (section, line))
        elif args.cmd == "forget":
            removed = ms.forget(MEM_DIR, " ".join(args.text), all_matches=args.all)
            if not removed:
                print("일치하는 줄이 없습니다.")
            else:
                print("지움 %d줄:" % len(removed))
                for line in removed:
                    print(line)
    except ms.MemoryRefused as e:
        print(str(e), file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
