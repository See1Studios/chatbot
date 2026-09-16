# chatbot

Sphere Hub NAS chat agent. **Self-maintain this project.**

GameDeveloper handoff (2026-09-16): day-to-day UI/host/persona/skill fixes belong here.

## Paths
- Code: `/volume1/homes/me/services/chatbot/`
- Data/workspace: `/volume1/homes/me/services/chatbot-data/`
- Hub FAB: `/volume1/web/index.html` (`AGY_CHAT_FAB_*` only)
- Persona publish: `/volume1/web/chat/persona/`
- Vendor (FAB): `/volume1/web/chat/vendor/`
- ctl: `/volume1/homes/me/services/chatbot-ctl.sh`
- Ports: 3011 (chat), 3012 (NAS MCP)

## Skills
- `chatbot-self-improve` — patch this project
- `task-observer` — observations under `skill-observations/`
- `nas-sphere` — NAS/Sphere ops

## Docs
- `/volume1/homes/me/services/chatbot/docs/DEVLOG.md`
- `/volume1/homes/me/services/chatbot/README.md`

## Rules
- Paths match product names (`chatbot`, not character names)
- Persona is swappable config
- Lore/IP surfaces = See1 only
- Chat bubble = user/assistant (+ status text while working); detailed tool lines → 로그 view
- Prefer restoring latest session over casual auto-create
- After changes: smoke healthz, note DEVLOG, optional OPEN observation
- Destructive ops (wipe sessions/persona, change ports): ask 실장님 first

## Version control (2026-09-16)
- `chatbot/` and `chatbot-data/workspace/` are now real git repos (git installed at `/volume1/@appstore/git/bin/git`, on `PATH` via `.bashrc`/`.profile`).
- **After a disk edit that used to get a `.bak-<label>-<ts>` sibling file: `git add <file> && git commit -m "<what/why>"` instead.** Don't create new `.bak-*` files — they're gitignored now and just clutter; use `git log`/`git diff`/`git checkout -- <file>` for history and rollback.
- Two separate repos on purpose (mirrors the code vs. data/workspace split above) — commit each from its own directory.
- `docs/DEVLOG.md` prose entries are still expected (git commit messages are terse; DEVLOG explains the why/story) — do both, they're complementary, not redundant.

## Self-modification
- 경계 문서: `SELF-MODIFY.md` (워크스페이스) / `chatbot/docs/SELF-MODIFY.md`
- 비상: `chatbot/docs/EMERGENCY.md` · `chatbot-ctl.sh repair|doctor|probe|guard`
- 코어 패치 후에도 `/message` 프로브 없이 끝내지 말 것 (`healthz`만으로는 부족)
