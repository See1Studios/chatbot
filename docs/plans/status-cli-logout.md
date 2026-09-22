# Status tab CLI logout (2026-09-22)

## API
`POST /api/accounts/logout` body `{"provider":"agy"|"claude"|"codex"|"grok"}`

Returns: `ok`, `provider`, `email_before`, `method`, `detail`, `providers` (fresh snapshot), `recycle`, optional `note`/`message_ko`. Never token values.

## Methods
| provider | method |
|----------|--------|
| agy | rename `~/.gemini/antigravity-cli/antigravity-oauth-token` → `*.bak-<epoch>`, then recycle owned procs (A30) |
| claude | `claude auth logout` |
| codex | `codex logout` |
| grok | `grok logout` |

## Login follow-up (not in this change)
- agy: Google account-chooser OAuth (`accounts.google.com` → `https://antigravity.google/oauth-callback`) then paste code into CLI/UI
- claude: browser OAuth URL → localhost:port/callback
- grok/codex: device-auth / API key

## Deploy on DiskStation
```bash
cd ~/services/chatbot && git pull --ff-only
# if pull brings sources already applied, skip patches; else:
bash apply_logout_patches.sh
# or: python3 ~/tmp/apply_accounts_logout.py  (full-file embed from box)
~/services/chatbot-ctl.sh repair   # already run by apply scripts
```

Cache bust: `static/index.html` → `app.js?v=109`.
