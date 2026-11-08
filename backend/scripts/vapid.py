"""Generate a VAPID key pair for browser push.

    uv run python scripts/vapid.py >> .env

Prints VAPID_PUBLIC_KEY (the browser's applicationServerKey) and VAPID_PRIVATE_KEY
(base64url DER, kept secret on the server: the worker and API).
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    v = Vapid()
    v.generate_keys()
    public = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = v.private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    print("# Browser push (Web Push). Keep VAPID_PRIVATE_KEY secret.")
    print(f"VAPID_PUBLIC_KEY={b64url(public)}")
    print(f"VAPID_PRIVATE_KEY={b64url(private)}")


if __name__ == "__main__":
    main()
