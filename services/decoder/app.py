from fastapi import FastAPI, Header
from pydantic import BaseModel
from typing import List
import os
import hmac
import hashlib
import requests
import time

app = FastAPI()

MAX_DECODE_TOKENS = int(os.getenv("MAX_DECODE_TOKENS", "200"))
DECODE_SECRET = os.getenv("DECODE_SECRET", "")
DECODE_SHARE_URL_A = os.getenv("DECODE_SHARE_URL_A", "http://aggregator_a:8002/clover/decode_share")
DECODE_SHARE_URL_R = os.getenv("DECODE_SHARE_URL_R", "http://aggregator_r:8003/clover/decode_share")
DECODE_ROUTER_SECRET = os.getenv("DECODE_ROUTER_SECRET", "")
DECODE_ROUTER_TOKEN = os.getenv("DECODE_ROUTER_TOKEN", "")
AUDIT_CALLER_TOKEN = os.getenv("AUDIT_CALLER_TOKEN", "")
AUDIT_TTL_SECONDS = int(os.getenv("AUDIT_TTL_SECONDS", "300"))


class DecodeRequest(BaseModel):
    round_id: int
    tokens: List[int]
    signature: str | None = None
    issued_at: int | None = None
    ttl_seconds: int | None = None
    request_id: str | None = None


def _signature_payload(round_id: int, tokens: List[int], issued_at: int, ttl_seconds: int) -> str:
    joined = ",".join(str(int(t)) for t in tokens)
    return f"{int(round_id)}:{int(issued_at)}:{int(ttl_seconds)}:{joined}"


def _signature(round_id: int, tokens: List[int], issued_at: int, ttl_seconds: int, secret: str) -> str:
    payload = _signature_payload(round_id, tokens, issued_at, ttl_seconds).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _router_signature(
    round_id: int,
    tokens: List[int],
    audit_tokens: List[int],
    signature: str,
    issued_at: int,
    ttl_seconds: int,
    secret: str,
) -> str:
    joined = ",".join(str(int(t)) for t in tokens)
    joined_audit = ",".join(str(int(t)) for t in audit_tokens)
    payload = f"{int(round_id)}:{int(issued_at)}:{int(ttl_seconds)}:{signature}:{joined}:{joined_audit}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _verify_auth(req: DecodeRequest) -> tuple[bool, str]:
    if not DECODE_SECRET:
        return False, "decode secret not configured"
    if not req.signature:
        return False, "missing signature"
    if req.issued_at is None or req.ttl_seconds is None:
        return False, "missing audit metadata"
    expected = _signature(req.round_id, req.tokens, req.issued_at, req.ttl_seconds, DECODE_SECRET)
    if not hmac.compare_digest(req.signature, expected):
        return False, "invalid signature"
    now = int(time.time())
    if now > int(req.issued_at) + int(req.ttl_seconds):
        return False, "signature expired"
    return True, ""


@app.post("/authorize_decode")
def authorize_decode(
    req: DecodeRequest,
    x_audit_caller: str | None = Header(default=None, alias="X-Audit-Caller"),
):
    if len(req.tokens) > MAX_DECODE_TOKENS:
        return {"ok": False, "error": "too many tokens", "max": MAX_DECODE_TOKENS}
    if not DECODE_SECRET:
        return {"ok": False, "error": "decode secret not configured"}
    if AUDIT_CALLER_TOKEN and x_audit_caller != AUDIT_CALLER_TOKEN:
        return {"ok": False, "error": "forbidden"}
    issued_at = int(time.time())
    ttl = max(1, AUDIT_TTL_SECONDS)
    signature = _signature(req.round_id, req.tokens, issued_at, ttl, DECODE_SECRET)
    return {
        "ok": True,
        "round_id": req.round_id,
        "signature": signature,
        "issued_at": issued_at,
        "ttl_seconds": ttl,
    }


@app.post("/verify_decode")
def verify_decode(req: DecodeRequest):
    ok, err = _verify_auth(req)
    if not ok:
        return {"ok": False, "error": err}
    return {"ok": True}


@app.post("/decode_tokens")
def decode_tokens(req: DecodeRequest):
    if len(req.tokens) > MAX_DECODE_TOKENS:
        return {"ok": False, "error": "too many tokens", "max": MAX_DECODE_TOKENS}
    ok, err = _verify_auth(req)
    if not ok:
        return {"ok": False, "error": err}

    if not req.request_id:
        payload = f"{req.round_id}:{req.signature}:{req.issued_at}:{req.ttl_seconds}:{','.join(str(int(t)) for t in req.tokens)}"
        req_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    else:
        req_id = req.request_id

    headers = {}
    if DECODE_ROUTER_TOKEN:
        headers["X-Decode-Token"] = DECODE_ROUTER_TOKEN
    secret = DECODE_ROUTER_SECRET or DECODE_ROUTER_TOKEN
    if secret:
        headers["X-Decode-Signature"] = _router_signature(
            req.round_id,
            req.tokens,
            req.tokens,
            req.signature or "",
            int(req.issued_at or 0),
            int(req.ttl_seconds or 0),
            secret,
        )

    try:
        resp_a = requests.post(
            DECODE_SHARE_URL_A,
            json={
                "round_id": req.round_id,
                "tokens": req.tokens,
                "audit_tokens": req.tokens,
                "signature": req.signature,
                "issued_at": req.issued_at,
                "ttl_seconds": req.ttl_seconds,
                "request_id": req_id,
            },
            headers=headers,
            timeout=5,
        )
        data_a = resp_a.json()
        if not data_a.get("ok"):
            return {"ok": False, "error": data_a.get("detail", "decode share A failed")}
        tokens_mid = data_a.get("tokens", [])
        share_sigs = data_a.get("signatures", [])

        if secret:
            headers["X-Decode-Signature"] = _router_signature(
                req.round_id,
                tokens_mid,
                req.tokens,
                req.signature or "",
                int(req.issued_at or 0),
                int(req.ttl_seconds or 0),
                secret,
            )
        resp_r = requests.post(
            DECODE_SHARE_URL_R,
            json={
                "round_id": req.round_id,
                "tokens": tokens_mid,
                "audit_tokens": req.tokens,
                "signature": req.signature,
                "issued_at": req.issued_at,
                "ttl_seconds": req.ttl_seconds,
                "request_id": req_id,
                "share_signatures": share_sigs,
            },
            headers=headers,
            timeout=5,
        )
        data_r = resp_r.json()
        if not data_r.get("ok"):
            return {"ok": False, "error": data_r.get("detail", "decode share R failed")}
        cells = data_r.get("cells", [])
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if len(cells) != len(req.tokens):
        return {"ok": False, "error": "decode length mismatch"}

    decoded = [[int(t), int(c)] for t, c in zip(req.tokens, cells)]
    return {"ok": True, "round_id": req.round_id, "count": len(decoded), "decoded": decoded}
