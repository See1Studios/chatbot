"""Web Push groundwork (push/A, push_manager.py): the VAPID key pair is made once and reused, subscriptions are kept
one per endpoint, and /api/push/* answers JSON. Every file lives in a temp folder, never the install's data.
Run: engine/run-tests.sh test_push
"""
import base64
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import host_config  # noqa: E402
import push_manager as P  # noqa: E402

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "au"}}


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class FakeHandler:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.sent = body, error, None

    def _read_json(self):
        if self.error:
            raise self.error
        return self.body

    def _send(self, code, raw, ctype):
        self.sent = (code, json.loads(raw.decode("utf-8")), ctype)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for name, value in (("PUSH_VAPID_FILE", self.dir / "push_vapid.json"),
                            ("PUSH_SUBSCRIPTIONS_FILE", self.dir / "push_subscriptions.json")):
            patcher = mock.patch.object(host_config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class VapidKeys(Base):
    def test_key_pair_is_p256_raw_urlsafe_and_unpadded(self):
        pub, priv = P.get_vapid_key_pair()
        self.assertNotIn("=", pub + priv)
        raw_pub, raw_priv = unb64(pub), unb64(priv)
        self.assertEqual((len(raw_pub), raw_pub[0], len(raw_priv)), (65, 4, 32))
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.derive_private_key(int.from_bytes(raw_priv, "big"), ec.SECP256R1())
        from cryptography.hazmat.primitives import serialization
        derived = key.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint)
        self.assertEqual(derived, raw_pub)

    def test_saved_once_then_reused(self):
        first = P.get_vapid_key_pair()
        saved = json.loads(host_config.PUSH_VAPID_FILE.read_text(encoding="utf-8"))
        self.assertEqual((saved["publicKey"], saved["privateKey"]), first)
        self.assertEqual(P.get_vapid_key_pair(), first)
        self.assertEqual(P.get_vapid_public_key(), first[0])

    def test_a_broken_key_file_is_an_error_not_a_new_key(self):
        # every browser subscription depends on the key: one that cannot be read this time must not be replaced
        # silently (review of #515) -- it is left as it is and the route answers with an error
        host_config.PUSH_VAPID_FILE.write_bytes(b"{not json")
        with self.assertRaises(RuntimeError):
            P.get_vapid_key_pair()
        self.assertEqual(host_config.PUSH_VAPID_FILE.read_bytes(), b"{not json")

    def test_the_key_file_is_private_from_its_first_byte(self):
        import os
        import stat
        P.get_vapid_key_pair()
        self.assertEqual(stat.S_IMODE(os.stat(str(host_config.PUSH_VAPID_FILE)).st_mode), 0o600)
        self.assertIn("os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600", (Path(P.__file__)).read_text(encoding="utf-8"))


class Subscriptions(Base):
    def test_add_dedupe_remove(self):
        self.assertEqual(P.get_subscriptions(), [])
        self.assertTrue(P.save_subscription(SUB))
        self.assertTrue(P.save_subscription(dict(SUB, keys={"p256dh": "new", "auth": "x"})))
        subs = P.get_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["keys"]["p256dh"], "new")
        self.assertTrue(P.save_subscription(dict(SUB, endpoint="https://push.example/other")))
        self.assertEqual(len(P.get_subscriptions()), 2)
        self.assertTrue(P.remove_subscription(SUB["endpoint"]))
        self.assertFalse(P.remove_subscription(SUB["endpoint"]))
        self.assertEqual([s["endpoint"] for s in P.get_subscriptions()], ["https://push.example/other"])

    def test_rejects_what_is_not_a_subscription(self):
        for bad in (None, {}, {"endpoint": "https://x"}, {"endpoint": "http://x", "keys": {}}, {"keys": {}}):
            self.assertFalse(P.save_subscription(bad), bad)
        self.assertFalse(host_config.PUSH_SUBSCRIPTIONS_FILE.exists())


class Routes(Base):
    def call(self, method, path, body=None, error=None):
        h = FakeHandler(body, error)
        handled = P.dispatch_push_api(h, method, path)
        return handled, h.sent

    def test_public_key_and_status(self):
        handled, (code, payload, ctype) = self.call("GET", "/api/push/vapid-public-key")
        self.assertTrue(handled)
        self.assertEqual((code, payload), (200, {"ok": True, "publicKey": P.get_vapid_public_key()}))
        self.assertIn("application/json", ctype)
        self.assertEqual(self.call("GET", "/api/push/status")[1][:2], (200, {"ok": True, "count": 0}))

    def test_subscribe_then_unsubscribe(self):
        self.assertEqual(self.call("POST", "/api/push/subscribe", {"subscription": SUB})[1][:2], (200, {"ok": True}))
        self.assertEqual(self.call("POST", "/api/push/subscribe", SUB)[1][:2], (200, {"ok": True}))
        self.assertEqual(self.call("GET", "/api/push/status")[1][1]["count"], 1)
        self.assertEqual(self.call("POST", "/api/push/unsubscribe", {"endpoint": SUB["endpoint"]})[1][:2],
                         (200, {"ok": True}))
        self.assertEqual(P.get_subscriptions(), [])

    def test_bad_bodies_get_errors(self):
        self.assertEqual(self.call("POST", "/api/push/subscribe", {"subscription": {}})[1][0], 400)
        self.assertEqual(self.call("POST", "/api/push/unsubscribe", {})[1][0], 400)
        err = ValueError("payload too large")
        err.status_code = 413
        self.assertEqual(self.call("POST", "/api/push/subscribe", error=err)[1][:2],
                         (413, {"ok": False, "error": "payload too large"}))

    def test_other_paths_fall_through(self):
        for method, path in (("GET", "/api/sessions"), ("POST", "/api/push/status"), ("GET", "/api/push/subscribe"),
                             ("GET", "/api/push/nope")):
            self.assertEqual(self.call(method, path), (False, None), (method, path))

    def test_test_route_triggers_notify(self):
        handled, (code, payload, _) = self.call("POST", "/api/push/test", {"title": "Hello", "body": "World"})
        self.assertTrue(handled)
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("count", payload)


class Delivery(Base):
    def test_send_notification_calls_endpoint_with_headers(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key = ec.generate_private_key(ec.SECP256R1())
        pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        sub = {"endpoint": "https://push.example/fake", "keys": {"p256dh": P._b64(pub), "auth": P._b64(b"1234567890123456")}}

        req_captured = []

        class FakeResponse:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=10):
            req_captured.append(req)
            return FakeResponse()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = P.send_notification(sub, {"title": "Hi", "body": "There"})
            self.assertTrue(ok)
            self.assertEqual(len(req_captured), 1)
            r = req_captured[0]
            self.assertEqual(r.get_full_url(), "https://push.example/fake")
            self.assertEqual(r.get_header("Content-encoding"), "aes128gcm")
            self.assertTrue(r.get_header("Authorization").startswith("vapid t="))

    def test_send_notification_prunes_on_410_gone(self):
        import urllib.error
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key = ec.generate_private_key(ec.SECP256R1())
        pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        sub = {"endpoint": "https://push.example/expired", "keys": {"p256dh": P._b64(pub), "auth": P._b64(b"1234567890123456")}}
        P.save_subscription(sub)
        self.assertEqual(len(P.get_subscriptions()), 1)

        def fake_urlopen(req, timeout=10):
            raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = P.send_notification(sub, "test message")
            self.assertFalse(ok)
            # Subscription should be automatically pruned
            self.assertEqual(P.get_subscriptions(), [])


class ServerWiring(unittest.TestCase):
    def test_server_routes_get_and_post(self):
        src = (ENGINE / "server.py").read_text(encoding="utf-8")
        self.assertIn("push_manager.dispatch_push_api(req.h, method, req.path)", src)
        self.assertIn('(None, _push("GET")),', src)
        self.assertIn('(None, _push("POST")),', src)


if __name__ == "__main__":
    unittest.main()
