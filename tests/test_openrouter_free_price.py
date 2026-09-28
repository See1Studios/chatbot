"""free_only also accepts a model the live catalog prices at 0, not only `:free` ids (a stealth model such as
`stealth/space-bunny-alpha` has no suffix). It fails closed: no catalog, no pricing, a non-zero or unreadable price
means not free, and the turn falls back to the free default (a money bug otherwise).
Run: python3 -m unittest tests.test_openrouter_free_price  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers.adapter_openai import OpenAIDialectAdapter, is_zero_priced  # noqa: E402

CATALOG = {
    "stealth/space-bunny-alpha": {"pricing": {"prompt": "0", "completion": "0"}},
    "z-ai/glm-5.2:free": {"pricing": {"prompt": "0", "completion": "0"}},
    "openrouter/auto": {"pricing": {"prompt": "-1", "completion": "-1"}},
    "vendor/paid": {"pricing": {"prompt": "0.000001", "completion": "0.000002"}},
    "vendor/image-billed": {"pricing": {"prompt": "0", "completion": "0", "image": "0.01"}},
    "vendor/no-pricing": {},
    "vendor/odd": {"pricing": {"prompt": "free", "completion": "0"}},
}


def adapter(catalog):
    a = OpenAIDialectAdapter(id="or", base_url="http://x/v1", api_key_env="NONE", default_model="z-ai/glm-5.2:free",
                             curated_models=["z-ai/glm-5.2:free", "stealth/space-bunny-alpha"], free_only=True)
    a._get_models_meta = lambda: catalog
    return a


class FreeByPrice(unittest.TestCase):
    def test_zero_price_is_free_and_anything_else_is_not(self):
        self.assertTrue(is_zero_priced(CATALOG["stealth/space-bunny-alpha"]))
        for mid in ("openrouter/auto", "vendor/paid", "vendor/image-billed", "vendor/no-pricing", "vendor/odd"):
            self.assertFalse(is_zero_priced(CATALOG[mid]), mid)
        self.assertFalse(is_zero_priced(None))

    def test_a_zero_priced_model_is_kept_and_listed(self):
        a = adapter(CATALOG)
        self.assertEqual(a.coerce_openrouter_model("stealth/space-bunny-alpha"), "stealth/space-bunny-alpha")
        self.assertIn("stealth/space-bunny-alpha", a.known_models())
        self.assertNotIn("vendor/paid", a.known_models())
        self.assertNotIn("openrouter/auto", a.known_models())

    def test_paid_or_unknown_models_fall_back_to_the_free_default(self):
        a = adapter(CATALOG)
        for mid in ("vendor/paid", "vendor/image-billed", "vendor/no-pricing", "openrouter/auto", "not/listed"):
            self.assertEqual(a.coerce_openrouter_model(mid), "z-ai/glm-5.2:free", mid)

    def test_without_the_catalog_only_the_id_counts(self):
        a = adapter({})                                    # fetch failed: remembered as empty
        self.assertEqual(a.coerce_openrouter_model("stealth/space-bunny-alpha"), "z-ai/glm-5.2:free")
        self.assertNotIn("stealth/space-bunny-alpha", a.known_models())
        b = adapter(CATALOG)
        b._get_models_meta = mock.Mock(side_effect=RuntimeError("boom"))
        self.assertEqual(b.coerce_openrouter_model("stealth/space-bunny-alpha"), "z-ai/glm-5.2:free")

    def test_a_model_that_turns_paid_is_dropped(self):
        catalog = dict(CATALOG)
        a = adapter(catalog)
        self.assertTrue(a.is_free("stealth/space-bunny-alpha"))
        catalog["stealth/space-bunny-alpha"] = {"pricing": {"prompt": "0.000003", "completion": "0.000015"}}
        self.assertFalse(a.is_free("stealth/space-bunny-alpha"))


if __name__ == "__main__":
    unittest.main()
