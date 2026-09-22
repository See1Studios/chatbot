"""Canary probe: which instruction/skill files does each provider CLI discover
on its own? Builds a throwaway git tree with a distinct canary token at every
level (repo root and spawn cwd) and every convention (AGENTS.md, CLAUDE.md,
.agents/skills, .claude/skills), spawns each provider with the host's own
build_args/build_env, and greps the reply for the tokens.

Results and what they proved: docs/providers/README.md + <provider>.md.

    python3 tests/probes/discovery_canary.py [agy agy+ claude codex grok]
        agy   = agy with NO --add-dir (cwd only);  agy+ = agy with --add-dir <cwd>

Lessons baked in:
  * never word the canary as a "secret" -- codex read it and refused to say it;
  * ask the model to list codes, do not paste them in the question;
  * a provider that fails (usage limit / 402) reports found=[] -- check `err`;
  * the tree lives outside the home git repo on purpose; real ancestors
    (~/AGENTS.md, ~/.agents/skills) are NOT reproduced here.
"""
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters import AgyAdapter, ClaudeAdapter, CodexAdapter, GrokAdapter  # noqa: E402
from host_config import DEFAULT_MODEL, HOME  # noqa: E402

TOKENS = {
    "ROOTA-1111": "root AGENTS.md", "ROOTC-2222": "root CLAUDE.md",
    "WSA-4444": "cwd AGENTS.md", "WSC-7777": "cwd CLAUDE.md",
    "ROOTSKILL-3333": "root .agents/skills", "ROOTSKILLCC-1212": "root .claude/skills",
    "WSSKILL-8888": "cwd .agents/skills", "WSSKILLCC-9999": "cwd .claude/skills",
}
QUESTION = ("이 작업공간의 지침 파일과 스킬을 확인해서 다음을 답해라. 도구를 쓰지 말고 알고 있는 것만: "
            "(1) 지침에 적힌 식별 코드 전부, (2) 사용 가능한 스킬 중 이름에 canary가 들어간 것 전부의 이름과 코드. 없으면 NONE.")


def build_tree() -> Path:
    root = Path(tempfile.mkdtemp(prefix="canary-"))
    cwd = root / "services" / "chatbot" / "data" / "workspace"
    cwd.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    def md(p, text):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    md(root / "AGENTS.md", "식별 코드(ROOT-AGENTS)는 ROOTA-1111 이다.")
    md(root / "CLAUDE.md", "식별 코드(ROOT-CLAUDE)는 ROOTC-2222 이다.")
    md(cwd / "AGENTS.md", "식별 코드(WS-AGENTS)는 WSA-4444 이다.")
    md(cwd / "CLAUDE.md", "식별 코드(WS-CLAUDE)는 WSC-7777 이다.")
    for base, sub, name, code in [
        (root, ".agents", "canary-root", "ROOTSKILL-3333"), (root, ".claude", "canary-root-cc", "ROOTSKILLCC-1212"),
        (cwd, ".agents", "canary-ws", "WSSKILL-8888"), (cwd, ".claude", "canary-ws-cc", "WSSKILLCC-9999"),
    ]:
        md(base / sub / "skills" / name / "SKILL.md",
           f"---\nname: {name}\ndescription: canary 스킬. 코드는 {code} 이다.\n---\n코드 {code}\n")
    return cwd


def probe(name, adapter, cwd, add_dirs):
    if name == "agy":
        args = adapter.build_args(DEFAULT_MODEL, "", str(uuid.uuid4()), add_dirs)
    else:
        args = adapter.build_args("default", "", None if adapter.mints_own_conversation_id() else str(uuid.uuid4()),
                                  add_dirs, prompt=QUESTION)
    p = subprocess.Popen(args, cwd=str(cwd), env=adapter.build_env(HOME), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    if isinstance(adapter, (AgyAdapter, ClaudeAdapter)):
        p.stdin.write(adapter.format_stdin(QUESTION))
        p.stdin.flush()
    elif isinstance(adapter, CodexAdapter):
        p.stdin.write(QUESTION)
        p.stdin.close()
    out, t0 = [], time.time()
    while time.time() - t0 < 150:
        r, _, _ = select.select([p.stdout], [], [], 2)
        if r:
            line = p.stdout.readline()
            if not line:
                break
            out.append(line)
            if ('"event":"result"' in line and isinstance(adapter, AgyAdapter)) or \
               ('"type":"result"' in line and isinstance(adapter, ClaudeAdapter)):
                break
        elif p.poll() is not None:
            break
    try:
        os.killpg(p.pid, 9)
    except OSError:
        pass
    raw = "".join(out)
    err = next((l.strip()[:120] for l in out if any(k in l for k in ("usage limit", "402", "Payment Required"))), "")
    found = sorted(TOKENS[t] for t in TOKENS if t in raw)
    print(f"{name:7s} found={found}" + (f"  err={err!r}" if err else ""), flush=True)


if __name__ == "__main__":
    which = sys.argv[1:] or ["agy", "agy+", "claude", "codex", "grok"]
    cwd = build_tree()
    try:
        if "agy" in which:
            probe("agy", AgyAdapter(), cwd, [])
        if "agy+" in which:
            probe("agy+", AgyAdapter(), cwd, [str(cwd)])
        if "claude" in which:
            probe("claude", ClaudeAdapter(), cwd, [])
        if "codex" in which:
            probe("codex", CodexAdapter(), cwd, [])
        if "grok" in which:
            probe("grok", GrokAdapter(), cwd, [])
    finally:
        shutil.rmtree(cwd.parents[3], ignore_errors=True)
