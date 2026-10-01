"""Web Push groundwork (push/A): the install's VAPID key pair and the browsers subscribed to it.

Keys live in host_config.PUSH_VAPID_FILE (made on first use), subscriptions in PUSH_SUBSCRIPTIONS_FILE, one per
endpoint. Both are written atomically. Routes: dispatch_push_api, called by server.py for GET and POST.
"""
from __future__ import annotations

import base64
import json
import os
import threading

import host_config
from artifact_manager import _atomic_write_text

_LOCK = threading.Lock()
PREFIX = "/api/push/"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, obj, private=False) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))
    if private:
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass


def _new_key_pair() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return {"publicKey": _b64(public), "privateKey": _b64(private)}


def get_vapid_key_pair() -> tuple:
    """(public_key_b64, private_key_b64): urlsafe base64 without padding; generated and saved on first call."""
    with _LOCK:
        keys = _read(host_config.PUSH_VAPID_FILE, {})
        if not (isinstance(keys, dict) and keys.get("publicKey") and keys.get("privateKey")):
            keys = _new_key_pair()
            _write(host_config.PUSH_VAPID_FILE, keys, private=True)
        return keys["publicKey"], keys["privateKey"]


def get_vapid_public_key() -> str:
    return get_vapid_key_pair()[0]


def get_subscriptions() -> list:
    subs = _read(host_config.PUSH_SUBSCRIPTIONS_FILE, [])
    return [s for s in subs if isinstance(s, dict) and s.get("endpoint")] if isinstance(subs, list) else []


def save_subscription(sub: dict) -> bool:
    """Store a PushSubscription ({"endpoint", "keys": {"p256dh", "auth"}}); the same endpoint replaces the old one.
    False when it is not a subscription."""
    if not (isinstance(sub, dict) and isinstance(sub.get("endpoint"), str) and sub["endpoint"].startswith("https://")
            and isinstance(sub.get("keys"), dict)):
        return False
    entry = {"endpoint": sub["endpoint"], "keys": sub["keys"]}
    with _LOCK:
        subs = [s for s in get_subscriptions() if s["endpoint"] != entry["endpoint"]] + [entry]
        _write(host_config.PUSH_SUBSCRIPTIONS_FILE, subs)
    return True


def remove_subscription(endpoint: str) -> bool:
    """True when `endpoint` was stored and is now gone."""
    with _LOCK:
        subs = get_subscriptions()
        kept = [s for s in subs if s["endpoint"] != endpoint]
        if len(kept) == len(subs):
            return False
        _write(host_config.PUSH_SUBSCRIPTIONS_FILE, kept)
    return True


def _route(handler, route):
    """(status, payload) for a push route, None when `route` is not one."""
    if route == ("GET", "vapid-public-key"):
        return 200, {"ok": True, "publicKey": get_vapid_public_key()}
    if route == ("GET", "status"):
        return 200, {"ok": True, "count": len(get_subscriptions())}
    if route not in (("POST", "subscribe"), ("POST", "unsubscribe")):
        return None
    try:
        body = handler._read_json()
    except Exception as e:  # noqa: BLE001 -- bad JSON, wrong Content-Type, too large
        return getattr(e, "status_code", 400), {"ok": False, "error": str(e)}
    body = body if isinstance(body, dict) else {}
    if route[1] == "subscribe":
        if save_subscription(body.get("subscription", body)):
            return 200, {"ok": True}
        return 400, {"ok": False, "error": "subscription needs an https endpoint and keys"}
    endpoint = body.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return 400, {"ok": False, "error": "endpoint required"}
    remove_subscription(endpoint)
    return 200, {"ok": True}


def dispatch_push_api(handler, method: str, path: str) -> bool:
    """Answer a /api/push/* request on `handler` (server.Handler: _send, _read_json). False: not a push route."""
    if not path.startswith(PREFIX):
        return False
    try:
        out = _route(handler, (method, path[len(PREFIX):]))
    except Exception as e:  # noqa: BLE001 -- e.g. the data folder is not writable
        out = 500, {"ok": False, "error": str(e)}
    if out is None:
        return False
    handler._send(out[0], json.dumps(out[1], ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
    return True
