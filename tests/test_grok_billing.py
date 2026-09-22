"""grok billing -> status-tab rows. The proxy speaks protobuf-JSON, which omits
zero-valued scalars, so an account at 0% used has NO creditUsagePercent.
Run: python3 -m unittest tests.test_grok_billing  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters import _grok_billing_to_rows  # noqa: E402

PERIOD = {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "2026-09-19T08:16:18+00:00", "end": "2026-09-26T08:16:18+00:00"}


class GrokBillingRows(unittest.TestCase):
    def test_zero_percent_used_arrives_as_absent_field_and_is_100_remaining(self):
        # exact shape returned live on 2026-09-19 for an account the TUI reports at 0% used
        cfg = {"currentPeriod": PERIOD, "onDemandCap": {"val": 0}, "onDemandUsed": {"val": 0},
               "isUnifiedBillingUser": True, "prepaidBalance": {"val": 0},
               "topUpMethod": "TOP_UP_METHOD_SAVED_PAYMENT_METHOD",
               "billingPeriodStart": PERIOD["start"], "billingPeriodEnd": PERIOD["end"]}
        rows = _grok_billing_to_rows({"config": cfg})
        self.assertEqual(rows, [{"group": "Grok", "limit_type": "주간", "remaining_pct": "100%", "reset_at": PERIOD["end"]}])

    def test_reported_percent_is_inverted_as_before(self):
        rows = _grok_billing_to_rows({"config": {"currentPeriod": PERIOD, "creditUsagePercent": 37.5}})
        self.assertEqual(rows[0]["remaining_pct"], "62%")

    def test_product_without_percent_is_zero_used_but_nameless_junk_is_skipped(self):
        cfg = {"currentPeriod": PERIOD, "productUsage": [
            {"product": "Build", "usagePercent": 20}, {"product": "Imagine"}, {"foo": 1}]}
        rows = _grok_billing_to_rows({"config": cfg})
        self.assertEqual([(r["group"], r["remaining_pct"]) for r in rows], [("Build", "80%"), ("Imagine", "100%")])

    def test_not_credits_shaped_stays_no_data_instead_of_inventing_a_bar(self):
        # the /billing?format=usage shape: nothing here says how much is left
        cfg = {"monthlyLimit": {"val": 0}, "used": {"val": 152}, "onDemandCap": {"val": 0}}
        self.assertEqual(_grok_billing_to_rows({"config": cfg}), [])
        self.assertEqual(_grok_billing_to_rows({"config": {}}), [])
        self.assertEqual(_grok_billing_to_rows({}), [])
        self.assertEqual(_grok_billing_to_rows([]), [])

    def test_full_usage_is_zero_remaining(self):
        rows = _grok_billing_to_rows({"config": {"currentPeriod": PERIOD, "creditUsagePercent": 100}})
        self.assertEqual(rows[0]["remaining_pct"], "0%")


if __name__ == "__main__":
    unittest.main()
