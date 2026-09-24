"""Providers: how each CLI or API brain is driven (FOLDERS_PROVIDERS_v1).

  adapters.py        the registry and get_adapter() -- import provider names from here
  adapter_base.py    AgentAdapter, common to every provider (no provider names)
  adapter_<id>.py    one per provider: agy, claude, grok, codex, openai (HTTP OpenAI dialect, data/providers.json)
  accounts.py        which account each CLI is logged in as, usage and quota rows
  account_login.py   logging a CLI in or out from the page
"""
