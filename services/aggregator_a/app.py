from __future__ import annotations

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Dict
import requests
import os
import math
import random
import logging
import hmac
import hashlib
from common.utils import derive_prp_seed_from_share, inv_prp
app = FastAPI()
seen = set()  # 存 (round_id, submission_id)


K = int(os.getenv("K", "50"))
KD = int(os.getenv("KD", "50"))
KPRIME = K + KD
DOMAIN = int(os.getenv("DOMAIN", "10000"))

MASK_BITS = int(os.getenv("MASK_BITS", "32"))
MASK = (1 << MASK_BITS) - 1

aggR_by_round: Dict[int, Dict[int, int]] = {}
logger = logging.getLogger("uvicorn.error")
logger = logging.getLogger("uvicorn.error")

# 这里放的是 R 的“基础地址”，我们拼 ?round_id=xxx
AGG_R_BASE = os.environ.get("AGG_R_BASE", "http://aggregator_r:8003/dump_share")
DECODE_ENABLE = os.getenv("DECODE_ENABLE", "1") == "1"
DECODE_AUDIT_URL = os.getenv("DECODE_AUDIT_URL", "http://decoder:8010/authorize_decode")
DECODE_URL = os.getenv("DECODE_URL", "http://decoder:8010/decode_tokens")
DECODE_VERIFY_URL = os.getenv("DECODE_VERIFY_URL", "http://decoder:8010/verify_decode")
DECODE_MAX = int(os.getenv("DECODE_MAX", "200"))
CLOVER_KEY_SHARE = os.getenv("CLOVER_KEY_SHARE", "")
CLOVER_CLIENT_TOKEN = os.getenv("CLOVER_CLIENT_TOKEN", "")
PRP_ROUNDS = int(os.getenv("PRP_ROUNDS", "8"))
DECODE_ROUTER_TOKEN = os.getenv("DECODE_ROUTER_TOKEN", "")
DECODE_ROUTER_SECRET = os.getenv("DECODE_ROUTER_SECRET", "")
DECODE_SHARE_MAX_PER_ROUND = int(os.getenv("DECODE_SHARE_MAX_PER_ROUND", "200"))
AUDIT_CALLER_TOKEN = os.getenv("AUDIT_CALLER_TOKEN", "")
SHARE_SIGN_SECRET = DECODE_ROUTER_SECRET or DECODE_ROUTER_TOKEN

def _decode_signature_payload(round_id: int, tokens: List[int]) -> str:
    joined = ",".join(str(int(t)) for t in tokens)
    return f"{int(round_id)}:{joined}"


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
def gaussian_noise(sigma: float) -> float:
    # Python 自带 random.gauss(mu, sigma)
    return random.gauss(0.0, sigma)

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
aggA_by_round: Dict[int, Dict[int, int]] = {}
received_by_round: Dict[int, int] = {}

# ✅ round_id -> final_map
final_by_round: Dict[int, Dict[int, int]] = {}
decode_count_by_round: Dict[int, int] = {}
decode_seen_tokens_by_round: Dict[int, set[int]] = {}
decode_cache_by_round: Dict[int, Dict[int, Dict[str, int | str]]] = {}
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

        # ✅ 去重：同一轮同一个 submission_id 只算一次
        if key in seen:
            skipped_dup += 1
            continue
        seen.add(key)

        m = aggA_by_round.setdefault(rid, {})
        for c, v in zip(r.idx, r.val):
            m[c] = (m.get(c, 0) + int(v)) & MASK

        received_by_round[rid] = received_by_round.get(rid, 0) + 1
        accepted += 1

    return {
        "ok": True,
        "rounds": len(aggA_by_round),
        "accepted": accepted,
        "skipped_duplicates": skipped_dup,
        "skipped_invalid": skipped_invalid,
        "invalid_samples": invalid_samples,
    }

@app.get("/rounds")
def rounds():
    rids = sorted(aggA_by_round.keys())
    return {"round_ids": rids, "count": len(rids)}

@app.get("/clover/key_share")
def clover_key_share(x_client_token: str | None = Header(default=None, alias="X-Client-Token")):
    if not CLOVER_KEY_SHARE:
        raise HTTPException(status_code=404, detail="key share not configured")
    if CLOVER_CLIENT_TOKEN and x_client_token != CLOVER_CLIENT_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    return {"ok": True, "share": CLOVER_KEY_SHARE}


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
    if len(req.tokens) > DECODE_MAX:
        raise HTTPException(status_code=400, detail="too many tokens")
    if len(req.tokens) != len(req.audit_tokens):
        raise HTTPException(status_code=400, detail="token length mismatch")
    ok, err = _verify_audit(req)
    if not ok:
        raise HTTPException(status_code=403, detail=err)

    rid = int(req.round_id)
    # 幂等：同 request_id 重放直接返回之前的结果
    req_cache = decode_request_cache_by_round.setdefault(rid, {})
    if req.request_id and req.request_id in req_cache:
        cached = req_cache[req.request_id]
        # 如果请求不一致，则拒绝
        if cached["tokens"] != req.tokens:
            raise HTTPException(status_code=409, detail="request_id already used with different tokens")
        return {
            "ok": True,
            "round_id": rid,
            "tokens": cached["mids"],
            "signatures": cached["sigs"],
        }

    token_cache = decode_cache_by_round.setdefault(rid, {})
    seen_tokens = decode_seen_tokens_by_round.setdefault(rid, set())
    missing = [int(t) for t in req.tokens if int(t) not in token_cache]
    used = len(seen_tokens)
    limit = max(0, DECODE_SHARE_MAX_PER_ROUND)
    if limit and used + len(missing) > limit:
        raise HTTPException(status_code=429, detail="decode quota exceeded")

    try:
        share = bytes.fromhex(CLOVER_KEY_SHARE)
    except Exception:
        raise HTTPException(status_code=500, detail="invalid key share format")

    seed_a = derive_prp_seed_from_share(req.round_id, share, DOMAIN, "A")
    auth_digest = hashlib.sha256((req.signature or "").encode("utf-8")).hexdigest()[:12]

    # 只计算缺失部分，其余走缓存
    for t in missing:
        try:
            token = int(t)
            mid = inv_prp(seed_a, token, DOMAIN, rounds=PRP_ROUNDS)
            sig = _share_signature(rid, token, mid, auth_digest, SHARE_SIGN_SECRET or "decode_share_sign")
            token_cache[token] = {"mid": mid, "sig": sig}
            seen_tokens.add(token)
        except Exception:
            raise HTTPException(status_code=400, detail=f"invalid token: {t}")

    mids = []
    sigs = []
    for t in req.tokens:
        cached = token_cache.get(int(t))
        if not cached:
            raise HTTPException(status_code=500, detail=f"cache missing token {t}")
        mids.append(int(cached["mid"]))
        sigs.append(str(cached["sig"]))

    decode_count_by_round[rid] = len(seen_tokens)
    logger.info(
        "decode_share_A rid=%s new=%s total_unique=%s auth=%s caller=%s",
        rid,
        len(missing),
        len(seen_tokens),
        auth_digest,
        (x_decode_token or "none"),
    )
    if req.request_id:
        req_cache[req.request_id] = {"tokens": list(req.tokens), "mids": mids, "sigs": sigs}
    return {"ok": True, "round_id": req.round_id, "tokens": mids, "signatures": sigs}

@app.get("/dumpA")
def dumpA(round_id: int):
    rid = int(round_id)
    m = aggA_by_round.get(rid, {})
    items = sorted(m.items(), key=lambda x: -x[1])[:50]
    return {"round_id": rid, "received_total": received_by_round.get(rid, 0), "top_cells_A_share": items}

@app.post("/reconstruct")
def reconstruct(round_id: int):
    rid = int(round_id)

    aggA = aggA_by_round.get(rid, {})
    # 从 R 拉这一轮的 share
    resp = requests.get(f"{AGG_R_BASE}?round_id={rid}", timeout=5)
    data = resp.json()
    aggR = data.get("aggR", {})

    out: Dict[int, int] = {}

    keys = set(aggA.keys())
    keys.update(int(k) for k in aggR.keys())

    for k in keys:
        a = aggA.get(k, 0)
        try:
            r = int(aggR.get(str(k), 0))
        except Exception:
            r = 0
        # JSON key 是字符串
        out[k] = (a + r) & MASK

    final_by_round[rid] = out
    return {"ok": True, "round_id": rid, "cells": len(out)}

@app.get("/dump")
def dump(round_id: int):
    rid = int(round_id)

    if rid in final_by_round:
        m = final_by_round[rid]
        items = sorted(m.items(), key=lambda x: -x[1])[:50]
        return {"mode": "final", "round_id": rid, "received_total": received_by_round.get(rid, 0), "top_cells": items}
    else:
        m = aggA_by_round.get(rid, {})
        items = sorted(m.items(), key=lambda x: -x[1])[:50]
        return {"mode": "A_share_only", "round_id": rid, "received_total": received_by_round.get(rid, 0), "top_cells": items}

@app.post("/reset_round")
def reset_round(round_id: int):
    rid = int(round_id)
    aggA_by_round.pop(rid, None)
    received_by_round.pop(rid, None)
    final_by_round.pop(rid, None)
    return {"ok": True, "round_id": rid}

@app.post("/reset_all")
def reset_all():
    aggA_by_round.clear()
    received_by_round.clear()
    final_by_round.clear()
    seen.clear()   # ✅ 清掉去重记录
    return {"ok": True}

@app.post("/reconstruct_latest")
def reconstruct_latest(expected: int = 200, min_cells: int = 1):
    # 1) latest rid
    if not aggA_by_round:
        return {"ok": False, "error": "no rounds in A yet"}

    rid = max(aggA_by_round.keys())

    # 2) A 侧检查
    received_A = received_by_round.get(rid, 0)
    aggA = aggA_by_round.get(rid, {})
    if received_A < expected:
        return {
            "ok": False,
            "error": "A not complete yet",
            "round_id": rid,
            "received_A": received_A,
            "expected": expected,
            "cells_in_A_map": len(aggA),
        }
    if len(aggA) < min_cells:
        return {
            "ok": False,
            "error": "A map too small",
            "round_id": rid,
            "received_A": received_A,
            "cells_in_A_map": len(aggA),
            "min_cells": min_cells,
        }

    # 3) R 侧拉取 + 检查
    r_url = f"{AGG_R_BASE}?round_id={rid}"
    try:
        resp = requests.get(r_url, timeout=5)
        http_status = resp.status_code
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {
            "ok": False,
            "error": "failed to fetch R",
            "round_id": rid,
            "r_url": r_url,
            "http_status": locals().get("http_status", None),
            "detail": str(e),
        }

    received_R = data.get("received_total", None)
    aggR = data.get("aggR", {})

    if received_R is None:
        return {
            "ok": False,
            "error": "R response missing received_total",
            "round_id": rid,
            "r_url": r_url,
            "http_status": http_status,
            "keys": list(data.keys())[:10],
        }

    if received_R < expected:
        return {
            "ok": False,
            "error": "R not complete yet",
            "round_id": rid,
            "received_A": received_A,
            "received_R": received_R,
            "expected": expected,
            "cells_in_A_map": len(aggA),
            "cells_in_R_map": (len(aggR) if isinstance(aggR, dict) else None),
        }

    if not isinstance(aggR, dict):
        return {
            "ok": False,
            "error": "R aggR is not a dict",
            "round_id": rid,
            "type_aggR": str(type(aggR)),
        }

    if len(aggR) < min_cells:
        return {
            "ok": False,
            "error": "R map too small",
            "round_id": rid,
            "received_R": received_R,
            "cells_in_R_map": len(aggR),
            "min_cells": min_cells,
        }

    # 4) 合并（A keys 是 int，R keys 是 str）
    out: Dict[int, int] = {}
    keys = set(aggA.keys())
    keysR = set()
    for k in aggR.keys():
        try:
            keysR.add(int(k))
        except Exception:
            pass
    keys.update(keysR)

    for k in keys:
        a = int(aggA.get(k, 0))
        r = int(aggR.get(str(k), 0))
        out[k] = (a + r) & MASK

    final_by_round[rid] = out

    return {
        "ok": True,
        "round_id": rid,
        "received_A": received_A,
        "received_R": received_R,
        "cells_in_A_map": len(aggA),
        "cells_in_R_map": len(aggR),
        "cells_in_final_map": len(out),
    }

@app.get("/dump_latest")
def dump_latest():
    if not aggA_by_round:
        return {"ok": False, "error": "no rounds in A yet"}

    rid = max(aggA_by_round.keys())

    if rid in final_by_round:
        m = final_by_round[rid]
        items = sorted(m.items(), key=lambda x: -x[1])[:50]
        return {"mode": "final", "round_id": rid, "received_total": received_by_round.get(rid, 0), "top_cells": items}
    else:
        m = aggA_by_round.get(rid, {})
        items = sorted(m.items(), key=lambda x: -x[1])[:50]
        return {"mode": "A_share_only", "round_id": rid, "received_total": received_by_round.get(rid, 0), "top_cells": items}
@app.get("/dump_latest_corrected")
def dump_latest_corrected():
    if not aggA_by_round:
        return {"ok": False, "error": "no rounds in A yet"}

    rid = max(aggA_by_round.keys())

    if rid not in final_by_round:
        return {"ok": False, "error": "latest round not reconstructed yet", "round_id": rid}

    final_map = final_by_round[rid]
    N_acc = received_by_round.get(rid, 0)

    E = (N_acc * KD) / DOMAIN  # 期望 dummy 偏置（这里通常是 1.0）

    corrected = {}
    for c, v in final_map.items():
        cv = v - E
        if cv > 0:
            corrected[c] = cv

    items = sorted(corrected.items(), key=lambda x: -x[1])[:50]
    return {
        "mode": "final_corrected",
        "round_id": rid,
        "received_total": N_acc,
        "E_dummy_per_cell": E,
        "top_cells": items
    }
@app.get("/dump_latest_corrected_thresholded")
def dump_latest_corrected_thresholded(tau: float = 3.0):
    if not aggA_by_round:
        return {"ok": False, "error": "no rounds in A yet"}

    rid = max(aggA_by_round.keys())

    if rid not in final_by_round:
        return {"ok": False, "error": "latest round not reconstructed yet", "round_id": rid}

    final_map = final_by_round[rid]
    N_acc = received_by_round.get(rid, 0)

    E = (N_acc * KD) / DOMAIN

    corrected = {}
    for c, v in final_map.items():
        cv = v - E
        if cv >= tau:
            corrected[c] = cv

    items = sorted(corrected.items(), key=lambda x: -x[1])[:50]
    return {
        "mode": "final_corrected_thresholded",
        "round_id": rid,
        "received_total": N_acc,
        "E_dummy_per_cell": E,
        "tau": tau,
        "cells_kept": len(corrected),
        "top_cells": items
    }


def laplace_noise(scale: float) -> float:
    # 生成 Laplace(0, scale)
    # 用 inverse CDF：u ~ Uniform(-0.5, 0.5) => n = -scale * sgn(u) * ln(1 - 2|u|)
    u = random.random() - 0.5
    return -scale * (1 if u >= 0 else -1) * math.log(1 - 2 * abs(u))

@app.get("/dump_latest_dp")
def dump_latest_dp(epsilon: float = 1.0, tau: float = 3.0, tau2: float = 3.0):
    if epsilon <= 0:
        return {"ok": False, "error": "epsilon must be > 0"}
    if tau2 < 0:
        return {"ok": False, "error": "tau2 must be >= 0"}

    if not aggA_by_round:
        return {"ok": False, "error": "no rounds in A yet"}

    rid = max(aggA_by_round.keys())

    if rid not in final_by_round:
        return {"ok": False, "error": "latest round not reconstructed yet", "round_id": rid}

    final_map = final_by_round[rid]
    # 在 final_map = final_by_round[rid] 之后立刻加：
    mx = max(final_map.values()) if final_map else 0
    if mx > DOMAIN:  # 真实计数不可能到这个量级（你这里 N=200）
        return {
            "ok": False,
            "error": "final_map looks like uint32 shares, not counts. Did you hit the wrong route or forget reconstruct?",
            "round_id": rid,
            "max_value": mx,
            "meta": {
                "N_acc": received_by_round.get(rid, 0),
                "K": K,
                "KD": KD,
                "DOMAIN": DOMAIN,
                "epsilon": epsilon,
                "tau": tau,
                "tau2": tau2,
            },
        }

    N_acc = received_by_round.get(rid, 0)

    # dummy 参数（与你 client_sim 一致）
    E = (N_acc * KD) / DOMAIN

    logger.info(
        "dump_latest_dp rid=%s N_acc=%s E=%.4f tau=%.4f tau2=%.4f",
        rid,
        N_acc,
        E,
        tau,
        tau2,
    )

    # 严谨化前提：你已实现 (round_id, submission_id) 去重 + cap_per_cell=1
    DELTA = 1.0
    scale = DELTA / epsilon

    dp_map = {}
    kept_pre = 0  # 通过 tau 的数量
    kept_post = 0 # 通过 tau2 的数量（最终发布）

    for c, v in final_map.items():
        # 1) dummy correction
        cv = v - E

        # 2) pre-threshold (tau)
        if cv < tau:
            continue
        kept_pre += 1

        # 3) add DP noise
        noisy = cv + laplace_noise(scale)

        # 4) clamp to 0 (post-processing)
        if noisy < 0:
            noisy = 0.0

        # 5) post-threshold (tau2)
        if noisy >= tau2:
            dp_map[c] = noisy
            kept_post += 1

    items = sorted(dp_map.items(), key=lambda x: -x[1])[:50]

    decode_error = None
    decoded_cells = []
    decoded_count = 0
    if DECODE_ENABLE and items:
        tokens = [c for c, _v in items][:DECODE_MAX]
        try:
            headers = {}
            if AUDIT_CALLER_TOKEN:
                headers["X-Audit-Caller"] = AUDIT_CALLER_TOKEN
            audit_resp = requests.post(
                DECODE_AUDIT_URL,
                json={"round_id": rid, "tokens": tokens},
                headers=headers,
                timeout=5,
            )
            audit_data = audit_resp.json()
            if not audit_data.get("ok"):
                decode_error = audit_data.get("error", "audit failed")
            else:
                signature = audit_data.get("signature")
                issued_at = audit_data.get("issued_at")
                ttl_seconds = audit_data.get("ttl_seconds")
                payload = {
                    "round_id": rid,
                    "tokens": tokens,
                    "signature": signature,
                    "issued_at": issued_at,
                    "ttl_seconds": ttl_seconds,
                }
                resp = requests.post(DECODE_URL, json=payload, timeout=5)
                data = resp.json()
                if not data.get("ok"):
                    decode_error = data.get("error", "decode failed")
                else:
                    decoded = {int(t): int(c) for t, c in data.get("decoded", [])}
                    decoded_cells = [
                        [decoded[t], v]
                        for t, v in items
                        if t in decoded
                    ]
                    decoded_count = len(decoded_cells)
        except Exception as e:
            decode_error = str(e)
    return {
        "mode": "dp_laplace_post_threshold",
        "round_id": rid,
        "received_total": N_acc,
        "E_dummy_per_cell": E,
        "tau": tau,
        "tau2": tau2,
        "epsilon": epsilon,
        "laplace_scale": scale,
        "cells_kept_pre": kept_pre,
        "cells_kept_post": kept_post,
        "N_acc": received_by_round.get(rid, 0),
        "K": K,
        "KD": KD,
        "DOMAIN": DOMAIN,
        "top_cells": decoded_cells if decoded_cells else items,
        "top_tokens": items,
        "decoded_count": decoded_count,
        "decoded_limit": (DECODE_MAX if DECODE_ENABLE else 0),
        "decode_error": decode_error,

    }
@app.get("/dump_latest_gaussian")
def dump_latest_gaussian(epsilon: float = 1.0, delta: float = 1e-6, tau: float = 3.0, tau2: float = 3.0):
    if epsilon <= 0:
        return {"ok": False, "error": "epsilon must be > 0"}
    if not (0 < delta < 1):
        return {"ok": False, "error": "delta must be in (0, 1)"}
    if tau2 < 0:
        return {"ok": False, "error": "tau2 must be >= 0"}

    if not aggA_by_round:
        return {"ok": False, "error": "no rounds in A yet"}

    rid = max(aggA_by_round.keys())
    if rid not in final_by_round:
        return {"ok": False, "error": "latest round not reconstructed yet", "round_id": rid}

    final_map = final_by_round[rid]
    N_acc = received_by_round.get(rid, 0)

    E = (N_acc * KD) / DOMAIN

    # 敏感度（你已通过去重 + cap=1 让 Δ=1 成立）
    DELTA = 1.0

    # Gaussian 机制的经典 sufficient bound
    sigma = (math.sqrt(2.0 * math.log(1.25 / delta)) * DELTA) / epsilon

    dp_map = {}
    kept_pre = 0
    kept_post = 0

    for c, v in final_map.items():
        cv = v - E
        if cv < tau:
            continue
        kept_pre += 1

        noisy = cv + gaussian_noise(sigma)

        if noisy < 0:
            noisy = 0.0

        if noisy >= tau2:
            dp_map[c] = noisy
            kept_post += 1

    items = sorted(dp_map.items(), key=lambda x: -x[1])[:50]

    decode_error = None
    decoded_cells = []
    decoded_count = 0
    if DECODE_ENABLE and items:
        tokens = [c for c, _v in items][:DECODE_MAX]
        try:
            headers = {}
            if AUDIT_CALLER_TOKEN:
                headers["X-Audit-Caller"] = AUDIT_CALLER_TOKEN
            audit_resp = requests.post(
                DECODE_AUDIT_URL,
                json={"round_id": rid, "tokens": tokens},
                headers=headers,
                timeout=5,
            )
            audit_data = audit_resp.json()
            if not audit_data.get("ok"):
                decode_error = audit_data.get("error", "audit failed")
            else:
                signature = audit_data.get("signature")
                issued_at = audit_data.get("issued_at")
                ttl_seconds = audit_data.get("ttl_seconds")
                payload = {
                    "round_id": rid,
                    "tokens": tokens,
                    "signature": signature,
                    "issued_at": issued_at,
                    "ttl_seconds": ttl_seconds,
                }
                resp = requests.post(DECODE_URL, json=payload, timeout=5)
                data = resp.json()
                if not data.get("ok"):
                    decode_error = data.get("error", "decode failed")
                else:
                    decoded = {int(t): int(c) for t, c in data.get("decoded", [])}
                    decoded_cells = [
                        [decoded[t], v]
                        for t, v in items
                        if t in decoded
                    ]
                    decoded_count = len(decoded_cells)
        except Exception as e:
            decode_error = str(e)
    return {
        "mode": "dp_gaussian_post_threshold",
        "round_id": rid,
        "received_total": N_acc,
        "E_dummy_per_cell": E,
        "tau": tau,
        "tau2": tau2,
        "epsilon": epsilon,
        "delta": delta,
        "gaussian_sigma": sigma,
        "cells_kept_pre": kept_pre,
        "cells_kept_post": kept_post,
        "top_cells": decoded_cells if decoded_cells else items,
        "top_tokens": items,
        "decoded_count": decoded_count,
        "decoded_limit": (DECODE_MAX if DECODE_ENABLE else 0),
        "decode_error": decode_error,
    }
@app.get("/stats_latest")
def stats_latest():
    if not received_by_round:
        return {"ok": False, "error": "no rounds yet"}

    rid = max(received_by_round.keys())

    # A 侧本轮累计到的 share-map
    mA = aggA_by_round.get(rid, {})

    # 你的 seen 是全局 set，元素是 (round_id, submission_id)
    unique_submissions = sum(1 for (r, _sid) in seen if r == rid)

    return {
        "ok": True,
        "round_id": rid,
        "received_total": received_by_round.get(rid, 0),
        "unique_submissions": unique_submissions,
        "cells_in_A_map": len(mA),
        "reconstructed": (rid in final_by_round),
        "cells_in_final_map": (len(final_by_round.get(rid, {})) if rid in final_by_round else 0),
    }
@app.get("/status_latest")
def status_latest():
    # 1) 选择 latest rid（优先用 aggA_by_round）
    if aggA_by_round:
        rid = max(aggA_by_round.keys())
    elif received_by_round:
        rid = max(received_by_round.keys())
    else:
        return {"ok": False, "error": "no rounds yet"}

    # 2) A 侧统计
    mA = aggA_by_round.get(rid, {})
    received_A = received_by_round.get(rid, 0)
    unique_submissions = sum(1 for (r, _sid) in seen if r == rid)

    # 3) R 侧拉取
    received_R = None
    cells_in_R_map = None
    r_fetch_ok = False
    r_error = None
    r_http_status = None
    r_url = f"{AGG_R_BASE}?round_id={rid}"
    aggR_sample_keys = None

    try:
        resp = requests.get(r_url, timeout=5)
        r_http_status = resp.status_code
        resp.raise_for_status()
        data = resp.json()

        received_R = data.get("received_total", None)
        aggR = data.get("aggR", {})
        cells_in_R_map = len(aggR)

        # 取几个 key 帮你确认返回结构
        if isinstance(aggR, dict):
            aggR_sample_keys = list(aggR.keys())[:3]

        r_fetch_ok = True

    except Exception as e:
        r_error = str(e)

    # 4) reconstruct 状态
    reconstructed = (rid in final_by_round)
    cells_in_final = len(final_by_round.get(rid, {})) if reconstructed else 0

    # 5) 返回统一仪表盘
    return {
        "ok": True,
        "round_id": rid,

        # A侧
        "received_A": received_A,
        "unique_submissions_A": unique_submissions,
        "cells_in_A_map": len(mA),

        # R侧
        "r_fetch_ok": r_fetch_ok,
        "r_url": r_url,
        "r_http_status": r_http_status,
        "received_R": received_R,
        "cells_in_R_map": cells_in_R_map,
        "aggR_sample_keys": aggR_sample_keys,
        "r_error": r_error,

        # 合并结果
        "reconstructed": reconstructed,
        "cells_in_final_map": cells_in_final,
    }
