from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Dict
import os
import logging
import hmac
import hashlib
import requests
from common.utils import seed_from_round, gaussian_preview, derive_prp_seed_from_share, inv_prp
app = FastAPI()
seen = set()  # 存 (round_id, submission_id) 用于去重
logger = logging.getLogger("uvicorn.error")

K = int(os.getenv("K", "50"))
KD = int(os.getenv("KD", "50"))
KPRIME = K + KD
DOMAIN = int(os.getenv("DOMAIN", "10000"))

MASK_BITS = int(os.getenv("MASK_BITS", "32"))
MASK = (1 << MASK_BITS) - 1
SEED_SECRET = os.getenv("RISERFL_SEED_SECRET", "rise_fed")
DEFAULT_M = int(os.getenv("RISERFL_M", "10"))
DEFAULT_DIM = int(os.getenv("RISERFL_DIM", "5"))
CLOVER_KEY_SHARE = os.getenv("CLOVER_KEY_SHARE", "")
CLOVER_CLIENT_TOKEN = os.getenv("CLOVER_CLIENT_TOKEN", "")
PRP_ROUNDS = int(os.getenv("PRP_ROUNDS", "8"))
DECODE_ROUTER_TOKEN = os.getenv("DECODE_ROUTER_TOKEN", "")
MAX_DECODE_TOKENS = int(os.getenv("MAX_DECODE_TOKENS", "200"))
DECODE_ROUTER_SECRET = os.getenv("DECODE_ROUTER_SECRET", "")
DECODE_VERIFY_URL = os.getenv("DECODE_VERIFY_URL", "http://decoder:8010/verify_decode")
DECODE_SHARE_MAX_PER_ROUND = int(os.getenv("DECODE_SHARE_MAX_PER_ROUND", "200"))
SHARE_SIGN_SECRET = DECODE_ROUTER_SECRET or DECODE_ROUTER_TOKEN

class Report(BaseModel):
    round_id: int
    submission_id: str
    idx: List[int] = Field(..., min_length=KPRIME, max_length=KPRIME)
    val: List[int] = Field(..., min_length=KPRIME, max_length=KPRIME)

class ForwardBatch(BaseModel):
    reports: List[Report]


class DecodeShareRequest(BaseModel):
    round_id: int
    tokens: List[int]
    audit_tokens: List[int]
    signature: str
    issued_at: int
    ttl_seconds: int
    request_id: str | None = None
    share_signatures: List[str] | None = None


# hard validation for idx range + uniqueness
def validate_report(r: Report):
    if len(r.idx) != KPRIME or len(r.val) != KPRIME:
        return "bad length"
    if len(set(r.idx)) != KPRIME:
        return "duplicate idx in one report"
    for c in r.idx:
        if not (0 <= int(c) < DOMAIN):
            return f"idx out of range: {c}"
    return None

# ✅ round_id -> (cell -> sum_share)
aggR_by_round: Dict[int, Dict[int, int]] = {}
received_by_round: Dict[int, int] = {}
decode_count_by_round: Dict[int, int] = {}
decode_seen_tokens_by_round: Dict[int, set[int]] = {}
decode_cache_by_round: Dict[int, Dict[int, int]] = {}
decode_request_cache_by_round: Dict[int, Dict[str, Dict[str, List[int] | str]]] = {}

@app.post("/forward")
def forward(batch: ForwardBatch):
    accepted = 0
    skipped_dup = 0
    skipped_invalid = 0
    invalid_samples = []

    for r in batch.reports:
        err = validate_report(r)
        if err:
            skipped_invalid += 1
            if len(invalid_samples) < 3:
                invalid_samples.append(err)
            continue
        rid = int(r.round_id)
        key = (rid, r.submission_id)

        if key in seen:
            skipped_dup += 1
            continue
        seen.add(key)

        # 1) report 内部去重/合并（防 idx 重复）
        local: Dict[int, int] = {}
        for c, v in zip(r.idx, r.val):
            c = int(c)
            v = int(v) & MASK
            local[c] = (local.get(c, 0) + v) & MASK

        # 2) 累加 share；不要在 share 上做 cap（会破坏重构）
        m = aggR_by_round.setdefault(rid, {})
        for c, v in local.items():
            m[c] = (m.get(c, 0) + v) & MASK

        received_by_round[rid] = received_by_round.get(rid, 0) + 1
        accepted += 1

    return {
        "ok": True,
        "rounds": len(aggR_by_round),
        "accepted": accepted,
        "skipped_duplicates": skipped_dup,
        "skipped_invalid": skipped_invalid,
        "invalid_samples": invalid_samples,
    }




@app.get("/rounds")
def rounds():
    rids = sorted(aggR_by_round.keys())
    return {"round_ids": rids, "count": len(rids)}

@app.get("/dump_share")
def dump_share(round_id: int):
    rid = int(round_id)
    agg = aggR_by_round.get(rid, {})
    return {
        "round_id": rid,
        "received_total": received_by_round.get(rid, 0),
        "aggR": {str(k): int(v) for k, v in agg.items()},
    }


@app.post("/reset_round")
def reset_round(round_id: int):
    rid = int(round_id)
    aggR_by_round.pop(rid, None)
    received_by_round.pop(rid, None)

    # 清掉该 round 的去重记录
    to_remove = [x for x in seen if x[0] == rid]
    for x in to_remove:
        seen.remove(x)

    return {"ok": True, "round_id": rid, "removed_seen": len(to_remove)}


@app.post("/reset_all")
def reset_all():
    aggR_by_round.clear()
    received_by_round.clear()
    seen.clear()
    return {"ok": True}

@app.get("/stats_latest")
def stats_latest():
    if not received_by_round:
        return {"ok": False, "error": "no rounds yet"}

    rid = max(received_by_round.keys())
    mR = aggR_by_round.get(rid, {})

    unique_submissions = sum(1 for (r, _sid) in seen if r == rid)

    return {
        "ok": True,
        "round_id": rid,
        "received_total": received_by_round.get(rid, 0),
        "unique_submissions": unique_submissions,
        "cells_in_R_map": len(mR),
    }

@app.get("/risefl/seed")
def risefl_seed(round_id: int):
    rid = int(round_id)
    seed = seed_from_round(rid, SEED_SECRET)
    return {"ok": True, "round_id": rid, "seed": seed}

@app.get("/risefl/gaussian_preview")
def risefl_gaussian_preview(round_id: int, m: int = DEFAULT_M, dim: int = DEFAULT_DIM, n: int = 3):
    rid = int(round_id)
    seed = seed_from_round(rid, SEED_SECRET)
    preview = gaussian_preview(seed, m, dim, n)
    return {
        "ok": True,
        "round_id": rid,
        "seed": seed,
        "m": m,
        "dim": dim,
        "n": n,
        "preview": preview,
    }

@app.get("/clover/key_share")
def clover_key_share(x_client_token: str | None = Header(default=None, alias="X-Client-Token")):
    if not CLOVER_KEY_SHARE:
        raise HTTPException(status_code=404, detail="key share not configured")
    if CLOVER_CLIENT_TOKEN and x_client_token != CLOVER_CLIENT_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    return {"ok": True, "share": CLOVER_KEY_SHARE}


def _router_signature_payload(
    round_id: int,
    tokens: List[int],
    audit_tokens: List[int],
    signature: str,
    issued_at: int,
    ttl_seconds: int,
) -> str:
    joined = ",".join(str(int(t)) for t in tokens)
    joined_audit = ",".join(str(int(t)) for t in audit_tokens)
    return f"{int(round_id)}:{int(issued_at)}:{int(ttl_seconds)}:{signature}:{joined}:{joined_audit}"


def _router_signature(
    round_id: int,
    tokens: List[int],
    audit_tokens: List[int],
    signature: str,
    issued_at: int,
    ttl_seconds: int,
    secret: str,
) -> str:
    payload = _router_signature_payload(round_id, tokens, audit_tokens, signature, issued_at, ttl_seconds).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _share_signature(round_id: int, token: int, mid: int, auth_digest: str, secret: str) -> str:
    payload = f"{int(round_id)}:{int(token)}:{int(mid)}:{auth_digest}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _verify_audit(req: DecodeShareRequest) -> tuple[bool, str]:
    try:
        resp = requests.post(
            DECODE_VERIFY_URL,
            json={
                "round_id": req.round_id,
                "tokens": req.audit_tokens,
                "signature": req.signature,
                "issued_at": req.issued_at,
                "ttl_seconds": req.ttl_seconds,
            },
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            return False, data.get("error", "audit verify failed")
        return True, ""
    except Exception as e:
        return False, str(e)


@app.post("/clover/decode_share")
def clover_decode_share(
    req: DecodeShareRequest,
    x_decode_token: str | None = Header(default=None, alias="X-Decode-Token"),
    x_decode_signature: str | None = Header(default=None, alias="X-Decode-Signature"),
):
    secret = DECODE_ROUTER_SECRET or DECODE_ROUTER_TOKEN
    if secret:
        if not x_decode_signature:
            raise HTTPException(status_code=403, detail="missing decode signature")
        expected = _router_signature(
            req.round_id,
            req.tokens,
            req.audit_tokens,
            req.signature,
            req.issued_at,
            req.ttl_seconds,
            secret,
        )
        if not hmac.compare_digest(x_decode_signature, expected):
            raise HTTPException(status_code=403, detail="invalid decode signature")
    if DECODE_ROUTER_TOKEN and x_decode_token != DECODE_ROUTER_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    if not CLOVER_KEY_SHARE:
        raise HTTPException(status_code=404, detail="key share not configured")
    if len(req.tokens) > MAX_DECODE_TOKENS:
        raise HTTPException(status_code=400, detail="too many tokens")
    if len(req.tokens) != len(req.audit_tokens):
        raise HTTPException(status_code=400, detail="token length mismatch")
    if not req.share_signatures or len(req.share_signatures) != len(req.tokens):
        raise HTTPException(status_code=400, detail="missing share signatures")
    ok, err = _verify_audit(req)
    if not ok:
        raise HTTPException(status_code=403, detail=err)

    rid = int(req.round_id)
    req_cache = decode_request_cache_by_round.setdefault(rid, {})
    if req.request_id and req.request_id in req_cache:
        cached = req_cache[req.request_id]
        if cached["tokens"] != req.tokens:
            raise HTTPException(status_code=409, detail="request_id already used with different tokens")
        return {"ok": True, "round_id": rid, "cells": cached["cells"]}

    token_cache = decode_cache_by_round.setdefault(rid, {})
    seen_tokens = decode_seen_tokens_by_round.setdefault(rid, set())

    auth_digest = hashlib.sha256((req.signature or "").encode("utf-8")).hexdigest()[:12]
    for mid, sig, orig in zip(req.tokens, req.share_signatures, req.audit_tokens):
        expected = _share_signature(rid, int(orig), int(mid), auth_digest, SHARE_SIGN_SECRET or "decode_share_sign")
        if not hmac.compare_digest(str(sig), expected):
            raise HTTPException(status_code=403, detail="invalid share signature")

    missing = [int(t) for t in req.tokens if int(t) not in token_cache]
    used = len(seen_tokens)
    limit = max(0, DECODE_SHARE_MAX_PER_ROUND)
    if limit and used + len(missing) > limit:
        raise HTTPException(status_code=429, detail="decode quota exceeded")

    try:
        share = bytes.fromhex(CLOVER_KEY_SHARE)
    except Exception:
        raise HTTPException(status_code=500, detail="invalid key share format")

    seed_r = derive_prp_seed_from_share(req.round_id, share, DOMAIN, "R")
    for t in missing:
        try:
            token = int(t)
            cell = inv_prp(seed_r, token, DOMAIN, rounds=PRP_ROUNDS)
            token_cache[token] = cell
            seen_tokens.add(token)
        except Exception:
            raise HTTPException(status_code=400, detail=f"invalid token: {t}")

    out = []
    for t in req.tokens:
        if int(t) not in token_cache:
            raise HTTPException(status_code=500, detail=f"cache missing token {t}")
        out.append(int(token_cache[int(t)]))

    decode_count_by_round[rid] = len(seen_tokens)
    logger.info(
        "decode_share_R rid=%s new=%s total_unique=%s auth=%s caller=%s",
        rid,
        len(missing),
        len(seen_tokens),
        auth_digest,
        (x_decode_token or "none"),
    )
    if req.request_id:
        req_cache[req.request_id] = {"tokens": list(req.tokens), "cells": out}
    return {"ok": True, "round_id": req.round_id, "cells": out}
