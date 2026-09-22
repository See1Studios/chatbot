# server.py ACCOUNTS_LOGIN_v1 insert points

1. After `import accounts` add: `import account_login`
2. Before GET `if path == "/api/accounts":` insert login/status handler
3. Before POST `if path == "/api/accounts/logout":` insert start/complete/cancel handlers

Preferred: run `/workspace/chatbot-login/apply_account_login.py` on the NAS via FIREBAT pipe deploy (embeds static UI + surgical server patch + repair).

Cache bump: `app.js?v=128`, `chat.css?v=27`.
