from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def decode_strict_json(payload: bytes) -> Any:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite JSON number")

    return json.loads(
        payload,
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )


class StrictJSONBodyMiddleware:
    """Bound request memory and reject ambiguous JSON before authentication logic."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        if not 0 < int(max_body_bytes) <= 16 * 1024 * 1024:
            raise ValueError("HTTP request body limit must be between 1 byte and 16 MiB")
        self.app = app
        self.max_body_bytes = int(max_body_bytes)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            bytes(name).lower(): bytes(value)
            for name, value in scope.get("headers", [])
        }
        content_encoding = headers.get(b"content-encoding", b"").strip().lower()
        if content_encoding not in {b"", b"identity"}:
            await JSONResponse(
                status_code=415,
                content={"detail": "encoded request bodies are not supported"},
            )(scope, receive, send)
            return
        declared_length = headers.get(b"content-length")
        if declared_length is not None:
            try:
                length = int(declared_length)
            except ValueError:
                length = -1
            if length < 0:
                await JSONResponse(
                    status_code=400,
                    content={"detail": "invalid Content-Length"},
                )(scope, receive, send)
                return
            if length > self.max_body_bytes:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "request body is too large"},
                )(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "request body is too large"},
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        media_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if body and (media_type == b"application/json" or media_type.endswith(b"+json")):
            try:
                decode_strict_json(bytes(body))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                await JSONResponse(
                    status_code=400,
                    content={"detail": "invalid JSON request body"},
                )(scope, receive, send)
                return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self.app(scope, replay, send)
