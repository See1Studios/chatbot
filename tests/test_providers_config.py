"""templates/providers.example.json holds together (PROVIDERS_CONFIG_v1, 2026-09-28; uds/F: an install's own
providers.json is user data in ~/.pe, so the shipped example is what is checked here).

A free-routed provider's advertised model list is `curated_models` plus whatever free models the
gateway currently offers, and the UI's default is the *first* of that list (server.py's
`/api/providers`). So an entry in `curated_models` that the gateway has retired keeps its place at
the front and stays the default: changing `default_model` alone did not move it, and a retired
`:free` model kept answering 404 after it had been "fixed" by that route alone.

What this file guards is the configuration's own hygiene, checkable with no network: the loader's
required fields, the default being curated, no paid route under `free_only` (a money bug), no
duplicates, no padding.

What it deliberately does NOT claim: that a live id is still free upstream. That is not knowable
locally -- the `:free` suffix is the only local signal, and a gateway can move a model to paid
without changing its id. A mutation check confirms it: putting the retired id back in
`curated_models` leaves this file green. Catching that needs a probe against the gateway's own
/models, which is a separate decision (doctor warns, or a test that reads a key) and not a test.
"""
import json
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
from providers.adapter_openai import is_openrouter_free_model  # noqa: E402

CONFIG = json.loads((CODE / "templates" / "providers.example.json").read_text(encoding="utf-8"))
DIALECTS = CONFIG["providers"]


class ProvidersConfig(unittest.TestCase):
    def test_every_dialect_has_the_fields_the_loader_requires(self):
        # providers/adapters.py::load_openai_dialect_adapters raises on a missing base_url or key env
        for pid, cfg in sorted(DIALECTS.items()):
            if cfg.get("type") != "openai_dialect":
                continue
            self.assertTrue(str(cfg.get("base_url") or "").strip(), "%s: no base_url" % pid)
            self.assertTrue(str(cfg.get("api_key_env") or "").strip(), "%s: no api_key_env" % pid)

    def test_the_default_model_is_one_of_the_curated_ones(self):
        # known_models() inserts the default at the front when it is missing, so this is about
        # explicitness, not about behaviour: a default that is not curated still leads the list.
        # What this file deliberately does NOT claim is catchable is a curated id the gateway has
        # retired -- see the module docstring.
        for pid, cfg in sorted(DIALECTS.items()):
            if not cfg.get("default_model"):
                continue
            self.assertIn(cfg["default_model"], cfg.get("curated_models") or [],
                          "%s: default_model is not in curated_models" % pid)

    def test_a_free_only_provider_curates_only_free_models(self):
        for pid, cfg in sorted(DIALECTS.items()):
            if not cfg.get("free_only"):
                continue
            for m in cfg.get("curated_models") or []:
                self.assertTrue(is_openrouter_free_model(m), "%s: %s is not a free route" % (pid, m))
            if cfg.get("default_model"):
                self.assertTrue(is_openrouter_free_model(cfg["default_model"]),
                                "%s: default_model %s is not a free route" % (pid, cfg["default_model"]))

    def test_no_duplicate_model_ids(self):
        for pid, cfg in sorted(DIALECTS.items()):
            models = cfg.get("curated_models") or []
            self.assertEqual(len(models), len(set(models)), "%s: duplicate curated ids" % pid)

    def test_no_curated_id_is_empty_or_has_surrounding_space(self):
        for pid, cfg in sorted(DIALECTS.items()):
            for m in cfg.get("curated_models") or []:
                self.assertEqual(m, m.strip(), "%s: %r has padding" % (pid, m))
                self.assertTrue(m, "%s: empty model id" % pid)


if __name__ == "__main__":
    unittest.main()
