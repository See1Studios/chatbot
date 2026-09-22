"""origin_guard.py: same-origin and CORS decisions.
Run: python3 -m unittest tests.test_origin_guard  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import origin_guard as og  # noqa: E402

HOST = "diskstation:3011"


class SameOriginTest(unittest.TestCase):
    def test_own_page_is_same_origin(self):
        self.assertTrue(og.same_origin("http://diskstation:3011", HOST))
        self.assertTrue(og.same_origin("http://DiskStation:3011", "diskstation:3011"))
        self.assertTrue(og.same_origin("http://192.168.0.5:3011", "192.168.0.5:3011"))
        self.assertTrue(og.same_origin("http://[::1]:3011", "[::1]:3011"))

    def test_other_ports_hosts_and_sites_are_not(self):
        for origin in ("http://diskstation", "http://diskstation:80", "http://diskstation:3012",
                       "http://evil.example:3011", "http://diskstation:3011.evil.example", "null", "", "://"):
            self.assertFalse(og.same_origin(origin, HOST), origin)

    def test_no_headers_at_all_is_refused(self):
        self.assertFalse(og.same_origin(None, HOST))
        self.assertFalse(og.same_origin(None, HOST, None))
        self.assertFalse(og.same_origin("http://diskstation:3011", None))
        self.assertFalse(og.same_origin("http://diskstation:3011", ""))

    def test_fetch_metadata_only_counts_without_an_origin(self):
        self.assertTrue(og.same_origin(None, HOST, "same-origin"))
        self.assertFalse(og.same_origin(None, HOST, "cross-site"))
        self.assertFalse(og.same_origin(None, HOST, "same-site"))
        self.assertFalse(og.same_origin("http://evil.example", HOST, "same-origin"))  # Origin wins

    def test_malformed_values_do_not_raise(self):
        self.assertFalse(og.same_origin("http://[bad", HOST))
        self.assertFalse(og.cors_allowed("http://[bad", HOST))


class CorsTest(unittest.TestCase):
    def test_pages_on_the_same_machine_may_read(self):
        for origin in ("http://diskstation", "http://diskstation:3011", "https://diskstation",
                       "http://diskstation:5000", "http://DISKSTATION:8080"):
            self.assertTrue(og.cors_allowed(origin, HOST), origin)
        self.assertTrue(og.cors_allowed("http://192.168.0.5", "192.168.0.5:3011"))

    def test_other_sites_may_not(self):
        for origin in ("http://evil.example", "http://diskstation.evil.example", "http://evildiskstation",
                       "null", "", None, "http://192.168.0.9"):
            self.assertFalse(og.cors_allowed(origin, HOST), origin)
        self.assertFalse(og.cors_allowed("http://diskstation", None))
        self.assertFalse(og.cors_allowed("http://diskstation", ""))


if __name__ == "__main__":
    unittest.main()
