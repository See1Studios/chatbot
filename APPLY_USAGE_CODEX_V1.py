#!/usr/bin/env python3
"""USAGE_v1 + CODEX_PROC_v1 + CODEX_MODELS_v1 deploy onto DiskStation chatbot.

Fixes:
1) First Status-tab /api/usage after CLI login fails (timeout/race/negative cache)
2) Codex orphan processes (node wrapper terminate without killpg; login/app-server strays)
3) Codex model dropdown empty (known_models() inherited [])

Usage on NAS:
  python3 APPLY_USAGE_CODEX_V1.py
  # expects payload/ beside this script OR /volume1/homes/me/tmp/usage-codex-v1/payload/
Then: bash chatbot-ctl.sh repair
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

CACHE = "132"
FILES = {
    "server.py": "server.py",
    "accounts.py": "accounts.py",
    "adapters.py": "adapters.py",
    "session.py": "session.py",
    "chatbot-ctl.sh": "chatbot-ctl.sh",
    "app.js": "static/app.js",
    "index.html": "static/index.html",
}
OPTIONAL = {
    "account_login.py": "account_login.py",
}

MARKERS = {
    "server.py": ("_invalidate_usage_cache", "USAGE_v1"),
    "accounts.py": ("reap_stray_cli_procs", "CODEX_PROC_v1"),
    "adapters.py": ("CODEX_MODELS_v1", "start_new_session=True"),
    "session.py": ("CODEX_PROC_v1", "start_new_session=True"),
    "chatbot-ctl.sh": ("CODEX_PROC_v1", "is_codex_bin"),
    "app.js": ("USAGE_v1", "timeoutMs: 55000"),
    "index.html": (f"app.js?v={CACHE}",),
}


def find_root() -> Path:
    for cand in (
        Path("/volume1/homes/me/services/chatbot"),
        Path("/var/services/homes/me/services/chatbot"),
        Path.home() / "services" / "chatbot",
    ):
        if (cand / "static" / "app.js").exists():
            return cand
    raise SystemExit("chatbot root not found")


def find_payload() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (
        here / "payload",
        Path("/volume1/homes/me/tmp/usage-codex-v1/payload"),
        Path("/var/services/homes/me/tmp/usage-codex-v1/payload"),
        Path.home() / "tmp" / "usage-codex-v1" / "payload",
    ):
        if (cand / "server.py").exists() and (cand / "adapters.py").exists():
            return cand
    raise SystemExit(
        "payload/ not found next to APPLY or under ~/tmp/usage-codex-v1/payload"
    )


def backup(path: Path, tag: str) -> Path:
    bak = path.with_name(f"{path.name}.bak-{tag}-{int(time.time())}")
    shutil.copy2(path, bak)
    print(f"backup {bak}")
    return bak


def install(src: Path, dst: Path, tag: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        backup(dst, tag)
    shutil.copy2(src, dst)
    if dst.suffix == ".sh" or dst.name.endswith(".sh"):
        dst.chmod(dst.stat().st_mode | 0o111)
    print(f"installed {dst} ({dst.stat().st_size} bytes)")


def verify(root: Path) -> None:
    for name, markers in MARKERS.items():
        rel = FILES.get(name) or OPTIONAL.get(name)
        if not rel:
            continue
        p = root / rel
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in markers:
            if m not in text:
                raise SystemExit(f"VERIFY FAIL {p}: missing {m!r}")
        print(f"verify OK {rel}")


def smoke(root: Path) -> None:
    sys.path.insert(0, str(root))
    import importlib
    for mod in ("adapters", "accounts"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import adapters
    import accounts

    models = adapters.get_adapter("codex").known_models()
    print(f"codex known_models ({len(models)}): {models}")
    if not models:
        raise SystemExit("codex known_models still empty")

    for pid in ("claude", "codex", "grok", "agy"):
        try:
            cur = accounts._ACCOUNT_FN[pid]()
            print(
                f"account[{pid}]: ok={cur.get('ok')} email={cur.get('email')} "
                f"plan={cur.get('plan')} err={cur.get('error')}"
            )
        except Exception as e:
            print(f"account[{pid}]: smoke err {e}")

    try:
        from adapters import get_adapter

        for pid in ("claude", "codex", "grok"):
            cur = accounts._ACCOUNT_FN[pid]()
            if not cur.get("ok"):
                print(f"usage[{pid}]: skip (not logged in)")
                continue
            t0 = time.time()
            rep = get_adapter(pid).rate_limit_report()
            dt = time.time() - t0
            ok = isinstance(rep, dict) and "error" not in rep and (
                rep.get("rows") is not None
            )
            print(
                f"usage[{pid}]: ok={ok} dt={dt:.1f}s "
                f"keys={list(rep.keys()) if isinstance(rep, dict) else type(rep)}"
            )
    except Exception as e:
        print(f"usage smoke skipped: {e}")

    try:
        snap = accounts.snapshot(providers=("codex", "claude", "grok"))
        for pid in ("codex", "claude", "grok"):
            procs = (snap.get("providers") or {}).get(pid, {}).get("processes") or []
            print(f"procs[{pid}]: {len(procs)}")
            for p in procs[:8]:
                print(
                    f"  pid={p.get('pid')} ppid={p.get('ppid')} owner={p.get('owner')} "
                    f"cmd={str(p.get('cmd') or '')[:100]}"
                )
    except Exception as e:
        print(f"proc smoke skipped: {e}")


def repair(root: Path) -> None:
    ctl = root / "chatbot-ctl.sh"
    if not ctl.exists():
        print("no chatbot-ctl.sh — skip repair")
        return
    print("running chatbot-ctl.sh repair …")
    r = subprocess.run(
        ["bash", str(ctl), "repair"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(r.stdout[-2000:] if r.stdout else "")
    if r.stderr:
        print(r.stderr[-1000:])
    print(f"repair exit={r.returncode}")


def main() -> None:
    tag = "usage-codex-v1"
    root = find_root()
    payload = find_payload()
    print(f"ROOT={root}")
    print(f"PAYLOAD={payload}")

    for name, rel in FILES.items():
        install(payload / name, root / rel, tag)
    for name, rel in OPTIONAL.items():
        src = payload / name
        if src.exists() and src.stat().st_size > 1000:
            dst = root / rel
            cur = dst.read_text(encoding="utf-8", errors="replace") if dst.exists() else ""
            install(src, dst, tag)

    verify(root)
    repair(root)
    verify(root)
    smoke(root)
    print(f"DONE cache=app.js?v={CACHE}")
    print("User: hard-refresh Status tab. Codex model dropdown should list gpt-5.6*.")
    print("Do NOT re-login Grok.")


if __name__ == "__main__":
    main()
