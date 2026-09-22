# Status-tab CLI LOGIN (agy / claude / codex / grok)

## API
- `POST /api/accounts/login/start` `{provider}`
- `POST /api/accounts/login/complete` `{provider, login_id?, code}`
- `POST /api/accounts/login/cancel` `{provider, login_id?}`
- `GET /api/accounts/login/status?provider=`

Modes: oauth_paste (agy), oauth_callback (claude), device_code (grok/codex).
Cache: app.js?v=128, chat.css?v=27. Deploy: apply_account_login.py via FIREBAT.
