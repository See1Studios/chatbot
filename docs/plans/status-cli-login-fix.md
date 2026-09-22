# Codex + Claude login fix

## Codex root cause (LIVE)
CSI color on URL/code → polluted authorize_url, user_code=null.

## Claude root cause (LIVE)
Needs oauth_paste (browser code), not oauth_callback. BEL duplicated URL.

## Deploy via FIREBAT
See patches/deploy-login-fix-from-firebat.ps1
Artifacts: /workspace/chatbot-login/APPLY_NOW.py
