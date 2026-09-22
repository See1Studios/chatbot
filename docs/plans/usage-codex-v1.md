# USAGE_v1 + CODEX_PROC_v1 + CODEX_MODELS_v1

See workspace `/workspace/chatbot-login/REPORT_USAGE_CODEX_V1.md` and tarball `usage-codex-v1.tgz`.

## Live evidence (pre-deploy)
- `codex models=[]` via `/api/providers`
- orphan `codex login --device-auth` ppid=1
- orphan/leaked `codex app-server` after usage
- cache v=131 → deploy bumps to **v=132**

## Deploy
FIREBAT: extract `usage-codex-v1.tgz` → `C:\Users\user\tmp-usage-codex-v1\` → `deploy-usage-codex-from-firebat.ps1`
Or pipe payload + `python3 APPLY_USAGE_CODEX_V1.py` on NAS then `chatbot-ctl.sh repair`.

Do not re-login Grok.
