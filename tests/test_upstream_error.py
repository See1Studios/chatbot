"""A gateway's own error text survives the trip (UPSTREAM_ERROR_v1, 2026-09-28).

An OpenAI-dialect gateway explains a 4xx in the response body -- "this model is unavailable for
free, the paid version is available now, use this slug instead" -- while urllib's own message is only
"HTTP Error 404: Not Found". The adapter read the stream without an except, so that body was dropped
and a retired model id presented as a bare 404 until someone picked the provider by hand.

Run: python3 -m unittest tests.test_upstream_error  (from services/chatbot)
"""
import io
import json
import unittest
import urllib.error
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
import sys  # noqa: E402
sys.path.insert(0, str(ENGINE))
from providers.adapter_openai import upstream_error_text  # noqa: E402


def http_error(code, body, reason="Not Found"):
    # The fp has to go through the constructor: addinfourl binds `read` at construction time, so
    # assigning .fp afterwards leaves read pointing at nothing.
    raw = body if isinstance(body, bytes) else body.encode("utf-8")
    return urllib.error.HTTPError("http://x/y", code, reason, {}, io.BytesIO(raw))


class Unreadable:
    def read(self, *a):
        raise OSError("body gone")

    def close(self):
        pass   # addinfourl closes the fp when it is collected; without this the test prints noise


class UpstreamErrorText(unittest.TestCase):
    def test_the_gateways_own_message_is_kept_with_the_status(self):
        body = json.dumps({"error": {"message": "This model is unavailable for free. "
                                                 "The paid version is available now - use this slug instead."}})
        out = upstream_error_text(http_error(404, body))
        self.assertIn("HTTP 404", out)
        self.assertIn("unavailable for free", out)
        self.assertIn("use this slug instead", out)
        self.assertNotIn("HTTP Error 404", out, "the bare urllib text is what we are replacing")

    def test_a_non_json_body_still_reaches_the_user(self):
        out = upstream_error_text(http_error(503, "upstream pool exhausted\n\ntry later"))
        self.assertIn("HTTP 503", out)
        self.assertIn("upstream pool exhausted", out)
        self.assertNotIn("\n", out, "newlines would break the one-line error notice")

    def test_an_empty_body_falls_back_to_the_reason(self):
        out = upstream_error_text(http_error(401, b"", reason="Unauthorized"))
        self.assertIn("HTTP 401", out)
        self.assertIn("Unauthorized", out)

    def test_a_body_that_cannot_be_read_does_not_hide_the_status(self):
        err = urllib.error.HTTPError("http://x/y", 500, "Server Error", {}, Unreadable())
        out = upstream_error_text(err)
        self.assertIn("HTTP 500", out)
        self.assertIn("Server Error", out)

    def test_the_detail_is_bounded(self):
        out = upstream_error_text(http_error(400, json.dumps({"error": {"message": "x" * 5000}})))
        self.assertLess(len(out), 400, "an upstream must not be able to flood the error line")


if __name__ == "__main__":
    unittest.main()
