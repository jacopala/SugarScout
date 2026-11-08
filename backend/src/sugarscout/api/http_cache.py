"""ETag revalidation for the dashboard's polled JSON.

The parent dashboard polls several endpoints every few seconds, and most answers do not
change between polls (the alerts list, for instance). Each JSON GET response gets a weak
ETag and `Cache-Control: no-cache`, so the browser stores the body but asks again every
time. When nothing changed the API answers 304 with no body, and `fetch` hands the
cached body back to the app as an ordinary 200.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

from fastapi import Request, Response


def etag_for(body: bytes) -> str:
    return 'W/"' + hashlib.blake2b(body, digest_size=16).hexdigest() + '"'


def _matches(if_none_match: str, etag: str) -> bool:
    """Weak comparison (RFC 9110 §13.1.2): ignore W/ prefixes; '*' matches anything."""
    want = etag.removeprefix("W/")
    for tag in if_none_match.split(","):
        tag = tag.strip()
        if tag == "*" or tag.removeprefix("W/") == want:
            return True
    return False


async def etag_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    if (
        request.method != "GET"
        or response.status_code != 200
        or not response.headers.get("content-type", "").startswith("application/json")
    ):
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
    etag = etag_for(body)
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    headers["etag"] = etag
    headers["cache-control"] = "no-cache"

    inm = request.headers.get("if-none-match")
    if inm and _matches(inm, etag):
        return Response(status_code=304, headers={"etag": etag, "cache-control": "no-cache"})
    return Response(content=body, status_code=200, headers=headers)
