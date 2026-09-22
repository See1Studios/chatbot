#!/usr/bin/env bash
set -euo pipefail
ROOT="${AGY_CHAT_ROOT:-$HOME/services/chatbot}"
EPOCH=$(date +%s)
cd "$ROOT"
here="$(cd "$(dirname "$0")" && pwd)"
PATCH_DIR="$here/patches"
[[ -d "$PATCH_DIR" ]] || PATCH_DIR="$ROOT/patches"
bak() { local f="$1"; [[ -f "$f" ]] && cp -a "$f" "$f.bak-$EPOCH" && echo "backup $f.bak-$EPOCH"; }
bak accounts.py
bak server.py
bak static/app.js
bak static/index.html
bak tests/test_accounts.py
patch -p0 < "$PATCH_DIR/accounts.py.diff"
patch -p0 < "$PATCH_DIR/server.py.diff"
patch -p0 < "$PATCH_DIR/static/app.js.diff"
patch -p0 < "$PATCH_DIR/static/index.html.diff"
patch -p0 < "$PATCH_DIR/tests/test_accounts.py.diff"
python3 -m py_compile accounts.py server.py
node --check static/app.js
python3 -m unittest tests.test_accounts.LogoutTest -v
"$HOME/services/chatbot-ctl.sh" repair
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
import accounts
r = accounts.logout("nope")
assert r["ok"] is False and "unknown" in r["error"], r
print("logout(nope) ok:", r)
import urllib.request
try:
  print("GET", urllib.request.urlopen("http://127.0.0.1:3011/api/accounts?provider=agy", timeout=8).status)
except Exception as e:
  print("GET smoke:", e)
print("DONE — do not POST real provider logout in smoke")
PY
