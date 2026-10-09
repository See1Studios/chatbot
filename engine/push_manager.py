"""Web Push groundwork (push/A): the install's VAPID key pair and the browsers subscribed to it.

Keys live in host_config.PUSH_VAPID_FILE (made on first use), subscriptions in PUSH_SUBSCRIPTIONS_FILE, one per
endpoint. Both are written atomically. Routes: dispatch_push_api, called by server.py for GET and POST.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple, Union

import host_config
from artifact_manager import _atomic_write_text

_LOCK = threading.Lock()
PREFIX = "/api/push/"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.urlsafe_b64decode(s)


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, obj, private=False) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if not private:
        _atomic_write_text(path, text)
        return
    # A private file is created 0600 and renamed into place: never readable by others, not even for a moment
    # (review of #515: written under the umask first, chmod after).
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise


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
        path = host_config.PUSH_VAPID_FILE
        if not path.exists():
            keys = _new_key_pair()
            _write(path, keys, private=True)
            return keys["publicKey"], keys["privateKey"]
        # The file is there: a key pair is never replaced because it could not be read this time -- every browser
        # subscribed to it would silently stop receiving (review of #515). A broken file is an error to look at.
        keys = _read(path, None)
        if not (isinstance(keys, dict) and keys.get("publicKey") and keys.get("privateKey")):
            raise RuntimeError("VAPID key file unreadable, not replaced: %s" % path)
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


def _vapid_auth_header(endpoint: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    _, priv_b64 = get_vapid_key_pair()
    priv_key = ec.derive_private_key(int.from_bytes(_unb64(priv_b64), "big"), ec.SECP256R1())
    parsed = urllib.parse.urlsplit(endpoint)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    hdr = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode("ascii"))
    claims = _b64(json.dumps({"aud": origin, "exp": int(time.time()) + 43200, "sub": "mailto:admin@localhost"},
                             separators=(",", ":")).encode("ascii"))
    signing_input = f"{hdr}.{claims}".encode("ascii")

    sig_der = priv_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(sig_der)
    sig_raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    jwt = f"{hdr}.{claims}.{_b64(sig_raw)}"
    return f"vapid t={jwt}, k={get_vapid_public_key()}"


def _encrypt_payload(sub: dict, payload_bytes: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    peer_pub_bytes = _unb64(sub["keys"]["p256dh"])
    peer_auth_bytes = _unb64(sub["keys"]["auth"])
    peer_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer_pub_bytes)

    local_priv = ec.generate_private_key(ec.SECP256R1())
    local_pub_bytes = local_priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    ecdh_secret = local_priv.exchange(ec.ECDH(), peer_pub)
    key_info = b"WebPush: info\x00" + peer_pub_bytes + local_pub_bytes
    prk = HKDF(algorithm=hashes.SHA256(), length=32, salt=peer_auth_bytes, info=key_info).derive(ecdh_secret)

    salt = os.urandom(16)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(prk)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(prk)

    padded = payload_bytes + b"\x02"
    ciphertext = AESGCM(cek).encrypt(nonce, padded, None)

    header = salt + (4096).to_bytes(4, "big") + bytes([len(local_pub_bytes)]) + local_pub_bytes
    return header + ciphertext


def send_notification(sub: dict, payload: Union[dict, str, bytes], timeout: int = 10) -> bool:
    """Send an encrypted Web Push message (RFC 8291 aes128gcm) to one subscription."""
    if not (isinstance(sub, dict) and isinstance(sub.get("endpoint"), str) and isinstance(sub.get("keys"), dict)):
        return False
    if isinstance(payload, dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = bytes(payload)

    endpoint = sub["endpoint"]
    try:
        encrypted_body = _encrypt_payload(sub, raw)
        vapid_auth = _vapid_auth_header(endpoint)
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Encoding": "aes128gcm",
            "TTL": "86400",
            "Urgency": "normal",
            "Authorization": vapid_auth,
        }
        req = urllib.request.Request(endpoint, data=encrypted_body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            remove_subscription(endpoint)
        return False
    except Exception:
        return False


def notify(title: str, body: str = "", url: str = "/", tag: str = "default", data: Optional[dict] = None) -> int:
    """Broadcast a push notification to all subscribed endpoints in the background."""
    subs = get_subscriptions()
    if not subs:
        return 0
    payload = {"title": title, "body": body, "url": url, "tag": tag}
    if data:
        payload["data"] = data

    def _send_all():
        for sub in subs:
            try:
                send_notification(sub, payload)
            except Exception:
                pass

    threading.Thread(target=_send_all, name="push-notify", daemon=True).start()
    return len(subs)


def _route(handler, route):
    """(status, payload) for a push route, None when `route` is not one."""
    if route == ("GET", "vapid-public-key"):
        return 200, {"ok": True, "publicKey": get_vapid_public_key()}
    if route == ("GET", "status"):
        return 200, {"ok": True, "count": len(get_subscriptions())}
    if route == ("POST", "test"):
        try:
            b = handler._read_json()
        except Exception:
            b = {}
        b = b if isinstance(b, dict) else {}
        count = notify(str(b.get("title") or "Private Engine"), str(b.get("body") or "Web Push test notification"),
                       str(b.get("url") or "/"), tag="test")
        return 200, {"ok": True, "count": count}
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
