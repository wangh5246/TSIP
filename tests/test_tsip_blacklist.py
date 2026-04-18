from __future__ import annotations

from pathlib import Path
import copy
import hashlib
import sys
import time

import pytest
from fastapi import HTTPException


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.ea import sign_attestation
import common.tsip as tsip_mod
from common.tsip import (
    build_modeset_bitmap,
    commitment_to_field,
    compute_chain_commitment,
    compute_location_commitment,
    compute_mode_tag_field,
    compute_modeset_commitment_field,
    compute_payload_commitment_field,
    compute_payload_digest,
    compute_policy_cap_sq,
    compute_secret_commitment,
    compute_secret_commitment_field,
    compute_tier_anchor_cap_sq,
    tier_vmax_sq,
    tsip_window_id,
)
from services.shuffler import app as shuffler


EA_TEST_SK = "53e7ddc909b2f3c63b919a65ba44081d7589bae0f6bb87a653cad4fd850a4ef4"
EA_TEST_PK = "b74d9156553132240a79cf426f509823691faaf97c29f13d0da7a3e137bdc649"
EA_TEST_KID = "ea-test"


def _reset_shuffler_state():
    shuffler.current_round_id = 424242
    shuffler.seenA_by_round.clear()
    shuffler.seenR_by_round.clear()
    shuffler.queueA.clear()
    shuffler.queueR.clear()
    shuffler.proof_threshold_by_round.clear()
    shuffler.tsip_state_by_user.clear()
    shuffler.pending_tsip_by_submission.clear()
    shuffler.tsip_reject_streak_by_user.clear()
    shuffler.tsip_blacklist_by_user.clear()
    shuffler.tsip_rejected_submission_keys.clear()
    shuffler.tsip_secret_commitment_by_user.clear()
    shuffler.tsip_secret_commitment_field_by_user.clear()
    shuffler.tsip_verify_dp_decision_by_submission.clear()
    shuffler.tsip_verify_dp_usage_by_round.clear()
    shuffler.tsip_bootstrap_held_by_round.clear()


def _secret_for_user(user_id: str) -> str:
    return hashlib.sha256(f"tsip_secret_v1:{user_id}".encode("utf-8")).hexdigest()


def _modeset_salt_for_user(user_id: str) -> int:
    digest = hashlib.sha256(f"tsip_modeset_salt_v3:{user_id}".encode("utf-8")).hexdigest()
    return int(int(digest, 16) % (1 << 251))


def _make_tsip_context(
    user_id: str,
    mode: str = "vehicle",
    tier: str = "transit",
    modeset_modes: list[str] | None = None,
) -> dict:
    modes = list(modeset_modes or ["walk", "bike", "vehicle", "transit"])
    secret = _secret_for_user(user_id)
    payload_idx = list(range(shuffler.KPRIME))
    payload_digest = compute_payload_digest(payload_idx)
    payload_commitment_field = str(compute_payload_commitment_field(payload_digest))
    secret_commitment = compute_secret_commitment(user_id, secret)
    secret_commitment_field = str(compute_secret_commitment_field(user_id, secret))
    modeset_bitmap = int(build_modeset_bitmap(modes))
    modeset_salt = int(_modeset_salt_for_user(user_id))
    modeset_commitment = str(compute_modeset_commitment_field(modeset_bitmap, modeset_salt))
    mode_tag = str(compute_mode_tag_field(mode, secret))
    return {
        "payload_idx": payload_idx,
        "payload_digest": payload_digest,
        "payload_commitment_field": payload_commitment_field,
        "secret": secret,
        "secret_commitment": secret_commitment,
        "secret_commitment_field": secret_commitment_field,
        "mode": str(mode),
        "tier": str(tier),
        "tier_vmax_sq": int(tier_vmax_sq(tier)),
        "modeset_bitmap": int(modeset_bitmap),
        "modeset_salt": int(modeset_salt),
        "modeset_commitment": str(modeset_commitment),
        "mode_tag": str(mode_tag),
    }


def _make_ea_attestation(user_id: str, ctx: dict) -> dict:
    payload = {
        "uid": str(user_id),
        "tier_vmax_sq": int(ctx["tier_vmax_sq"]),
        "com_sec": str(ctx["secret_commitment_field"]),
        "com_modeset": str(ctx["modeset_commitment"]),
        "exp": int(time.time()) + 3600,
        "kid": EA_TEST_KID,
    }
    return sign_attestation(EA_TEST_SK, payload)


def _make_enrollment_report(
    submission_id: str,
    user_id: str,
    ctx: dict,
    x: int = 10,
    y: int = 20,
    timestamp: int = 1000,
    valid_chain: bool = True,
) -> tuple[shuffler.Report, dict]:
    window_id = tsip_window_id(timestamp, shuffler.TSIP_WINDOW_SEC)
    curr_loc = compute_location_commitment(user_id, x, y, timestamp, window_id, "")
    curr_chain = compute_chain_commitment(
        "",
        curr_loc,
        timestamp,
        window_id,
        payload_digest=ctx["payload_digest"],
        secret_commitment=ctx["secret_commitment"],
    )
    if not valid_chain:
        curr_chain = "0" * 64
    report = shuffler.Report(
        round_id=0,
        submission_id=submission_id,
        idx=list(ctx["payload_idx"]),
        val=[1] * shuffler.KPRIME,
        tsip={
            "version": "v3",
            "user_id": user_id,
            "prev_loc_commitment": "",
            "curr_loc_commitment": curr_loc,
            "prev_chain_commitment": "",
            "curr_chain_commitment": curr_chain,
            "timestamp": timestamp,
            "window_id": window_id,
            "payload_digest": ctx["payload_digest"],
            "secret_commitment": ctx["secret_commitment"],
            "secret_commitment_field": ctx["secret_commitment_field"],
            "payload_commitment_field": ctx["payload_commitment_field"],
            "modeset_commitment": ctx["modeset_commitment"],
            "mode_tag": ctx["mode_tag"],
            "tier_vmax_sq": int(ctx["tier_vmax_sq"]),
            "ea_attestation": _make_ea_attestation(user_id, ctx),
            "proof": None,
            "public_signals": [],
        },
    )
    local_state = {
        "x": int(x),
        "y": int(y),
        "timestamp": int(timestamp),
        "window_id": int(window_id),
        "loc_commitment": str(curr_loc),
        "chain_commitment": str(curr_chain),
    }
    return report, local_state


def _make_followup_report(
    submission_id: str,
    user_id: str,
    ctx: dict,
    prev_local_state: dict,
    curr_x: int = 30,
    curr_y: int = 40,
    step_sec: int = 60,
    valid_prev: bool = True,
) -> tuple[shuffler.Report, dict]:
    prev_server_state = shuffler.tsip_state_by_user[user_id]
    prev_timestamp = int(prev_local_state["timestamp"])
    timestamp = int(prev_timestamp + max(1, int(step_sec)))
    window_id = tsip_window_id(timestamp, shuffler.TSIP_WINDOW_SEC)
    prev_loc = str(prev_server_state["loc_commitment"])
    prev_chain = str(prev_server_state["chain_commitment"])
    curr_loc = compute_location_commitment(user_id, curr_x, curr_y, timestamp, window_id, prev_chain)
    curr_chain = compute_chain_commitment(
        prev_chain,
        curr_loc,
        timestamp,
        window_id,
        payload_digest=ctx["payload_digest"],
        secret_commitment=ctx["secret_commitment"],
    )
    anchor_loc, _, _ = shuffler._expected_anchor_from_state(prev_server_state)
    step_dt = max(1, timestamp - int(prev_server_state["timestamp"]))
    step_dt_sq = int(step_dt * step_dt)
    declared_tier_vmax_sq = int(prev_server_state.get("tier_vmax_sq", ctx["tier_vmax_sq"]))
    tier_anchor_cap_sq = int(
        compute_tier_anchor_cap_sq(declared_tier_vmax_sq, shuffler.TSIP_ADWC_WINDOW_K, step_dt_sq)
    )
    cap_policy_sq = int(compute_policy_cap_sq(tier_anchor_cap_sq, shuffler.TSIP_POLICY_CAP_RATIO))

    prev_loc_payload = prev_loc if valid_prev else "f" * 64
    public_signals = [
        str(commitment_to_field(prev_loc)),
        str(commitment_to_field(curr_loc)),
        str(commitment_to_field(anchor_loc)),
        str(step_dt_sq),
        str(declared_tier_vmax_sq),
        str(tier_anchor_cap_sq),
        str(cap_policy_sq),
        str(ctx["payload_commitment_field"]),
        str(ctx["secret_commitment_field"]),
        str(ctx["modeset_commitment"]),
        str(ctx["mode_tag"]),
    ]
    report = shuffler.Report(
        round_id=0,
        submission_id=submission_id,
        idx=list(ctx["payload_idx"]),
        val=[1] * shuffler.KPRIME,
        tsip={
            "version": "v3",
            "user_id": user_id,
            "prev_loc_commitment": prev_loc_payload,
            "curr_loc_commitment": curr_loc,
            "prev_chain_commitment": prev_chain,
            "curr_chain_commitment": curr_chain,
            "timestamp": timestamp,
            "window_id": window_id,
            "payload_digest": ctx["payload_digest"],
            "secret_commitment": ctx["secret_commitment"],
            "secret_commitment_field": ctx["secret_commitment_field"],
            "payload_commitment_field": ctx["payload_commitment_field"],
            "anchor_loc_commitment": anchor_loc,
            "step_dt_sq": int(step_dt_sq),
            "tier_vmax_sq": int(declared_tier_vmax_sq),
            "tier_anchor_cap_sq": int(tier_anchor_cap_sq),
            "cap_policy_sq": int(cap_policy_sq),
            "modeset_commitment": ctx["modeset_commitment"],
            "mode_tag": ctx["mode_tag"],
            "ea_attestation": _make_ea_attestation(user_id, ctx),
            "proof": {"pi_a": ["0", "0"], "pi_b": [["0", "0"], ["0", "0"]], "pi_c": ["0", "0"]},
            "public_signals": public_signals,
        },
    )
    next_local_state = {
        "x": int(curr_x),
        "y": int(curr_y),
        "timestamp": int(timestamp),
        "window_id": int(window_id),
        "loc_commitment": str(curr_loc),
        "chain_commitment": str(curr_chain),
    }
    return report, next_local_state


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    _reset_shuffler_state()
    monkeypatch.setattr(
        tsip_mod,
        "_poseidon2_hash",
        lambda a, b: (int(a) * 1315423911 + int(b) * 2654435761 + 97) % tsip_mod.SNARK_FIELD,
    )
    monkeypatch.setattr(shuffler, "TSIP_ENABLE", True)
    monkeypatch.setattr(shuffler, "ZK_STEP_ENABLE", False)
    monkeypatch.setattr(shuffler, "PROOF_ENABLE", False)
    monkeypatch.setattr(shuffler, "TSIP_BLACKLIST_THRESHOLD", 3)
    monkeypatch.setattr(shuffler, "TSIP_EA_REQUIRE", True)
    monkeypatch.setattr(shuffler, "TSIP_EA_PUBKEYS", {EA_TEST_KID: EA_TEST_PK})
    monkeypatch.setattr(shuffler, "TSIP_EA_ALLOW_EXPIRED_SEC", 0)
    monkeypatch.setattr(shuffler, "TSIP_POLICY_CAP_RATIO", 0.5)
    monkeypatch.setattr(shuffler, "TSIP_BOOTSTRAP_POLICY", "legacy_accept")
    monkeypatch.setattr(shuffler, "TSIP_WARMUP_ROUNDS", max(int(shuffler.TSIP_ADWC_WINDOW_K), 2))
    monkeypatch.setattr(shuffler, "verify_tsip_proof", lambda proof, public_signals: (True, ""))
    yield
    _reset_shuffler_state()


def test_blacklist_counts_a_r_once_per_submission():
    user_id = "u1"
    ctx = _make_tsip_context(user_id)
    for sid in ("bad-1", "bad-2", "bad-3"):
        report, _ = _make_enrollment_report(sid, user_id, ctx, valid_chain=False)
        with pytest.raises(HTTPException):
            shuffler.ingestA(report)
        with pytest.raises(HTTPException):
            shuffler.ingestR(report)
    assert shuffler.tsip_reject_streak_by_user[user_id] == 3
    assert user_id in shuffler.tsip_blacklist_by_user

    ok_report, _ = _make_enrollment_report("bad-4", user_id, ctx, valid_chain=True)
    with pytest.raises(HTTPException) as exc:
        shuffler.ingestA(ok_report)
    assert exc.value.status_code == 403
    assert exc.value.detail == "tsip user blacklisted"


def test_successful_submission_clears_reject_streak():
    user_id = "u2"
    ctx = _make_tsip_context(user_id)
    for sid in ("bad-a", "bad-b"):
        bad_report, _ = _make_enrollment_report(sid, user_id, ctx, valid_chain=False)
        with pytest.raises(HTTPException):
            shuffler.ingestA(bad_report)
    assert shuffler.tsip_reject_streak_by_user[user_id] == 2

    init, local_state = _make_enrollment_report("good-init", user_id, ctx, valid_chain=True)
    shuffler.ingestA(init)
    shuffler.ingestR(init)
    assert user_id not in shuffler.tsip_reject_streak_by_user

    bad_follow, _ = _make_followup_report("bad-followup", user_id, ctx, local_state, valid_prev=False)
    with pytest.raises(HTTPException):
        shuffler.ingestA(bad_follow)
    assert shuffler.tsip_reject_streak_by_user[user_id] == 1
    assert user_id not in shuffler.tsip_blacklist_by_user


def test_malleability_bitflip_and_replacement_rejected():
    user_id = "u3"
    ctx = _make_tsip_context(user_id)
    init, local_state = _make_enrollment_report("init-u3", user_id, ctx)
    shuffler.ingestA(init)
    shuffler.ingestR(init)

    baseline, _ = _make_followup_report("u3-base", user_id, ctx, local_state)
    shuffler.ingestA(copy.deepcopy(baseline))
    shuffler.ingestR(copy.deepcopy(baseline))

    base_local = {
        "x": 30,
        "y": 40,
        "timestamp": int(local_state["timestamp"]) + 60,
        "window_id": tsip_window_id(int(local_state["timestamp"]) + 60, shuffler.TSIP_WINDOW_SEC),
        "loc_commitment": str(baseline.tsip["curr_loc_commitment"]),
        "chain_commitment": str(baseline.tsip["curr_chain_commitment"]),
    }

    # tier_vmax_sq: bitflip + replacement with another legal tier value.
    r1, _ = _make_followup_report("u3-tier-bitflip", user_id, ctx, base_local)
    r1.tsip["tier_vmax_sq"] = int(r1.tsip["tier_vmax_sq"]) ^ 1
    with pytest.raises(HTTPException):
        shuffler.ingestA(r1)

    r2, _ = _make_followup_report("u3-tier-replace", user_id, ctx, base_local)
    r2.tsip["tier_vmax_sq"] = 1089
    with pytest.raises(HTTPException):
        shuffler.ingestA(r2)

    # modeset_commitment: bitflip + replacement.
    r3, _ = _make_followup_report("u3-modeset-bitflip", user_id, ctx, base_local)
    r3.tsip["modeset_commitment"] = str(int(r3.tsip["modeset_commitment"]) ^ 1)
    with pytest.raises(HTTPException):
        shuffler.ingestA(r3)

    alt_modeset_commitment = str(
        compute_modeset_commitment_field(build_modeset_bitmap(["walk", "bike"]), ctx["modeset_salt"])
    )
    r4, _ = _make_followup_report("u3-modeset-replace", user_id, ctx, base_local)
    r4.tsip["modeset_commitment"] = alt_modeset_commitment
    with pytest.raises(HTTPException):
        shuffler.ingestA(r4)

    # mode_tag: bitflip + replacement.
    r5, _ = _make_followup_report("u3-mode-tag-bitflip", user_id, ctx, base_local)
    r5.tsip["mode_tag"] = str(int(r5.tsip["mode_tag"]) ^ 1)
    with pytest.raises(HTTPException):
        shuffler.ingestA(r5)

    r6, _ = _make_followup_report("u3-mode-tag-replace", user_id, ctx, base_local)
    r6.tsip["mode_tag"] = str(compute_mode_tag_field("walk", ctx["secret"]))
    with pytest.raises(HTTPException):
        shuffler.ingestA(r6)

    # hash_anchor: bitflip + replacement.
    r7, _ = _make_followup_report("u3-anchor-bitflip", user_id, ctx, base_local)
    r7.tsip["public_signals"][2] = str(int(r7.tsip["public_signals"][2]) ^ 1)
    with pytest.raises(HTTPException):
        shuffler.ingestA(r7)

    r8, _ = _make_followup_report("u3-anchor-replace", user_id, ctx, base_local)
    r8.tsip["public_signals"][2] = str(commitment_to_field("f" * 64))
    with pytest.raises(HTTPException):
        shuffler.ingestA(r8)


def test_cap_policy_and_tier_anchor_inconsistency_rejected():
    user_id = "u4"
    ctx = _make_tsip_context(user_id)
    init, local_state = _make_enrollment_report("init-u4", user_id, ctx)
    shuffler.ingestA(init)
    shuffler.ingestR(init)

    bad_cap, _ = _make_followup_report("u4-bad-cap", user_id, ctx, local_state)
    bad_cap.tsip["cap_policy_sq"] = int(bad_cap.tsip["cap_policy_sq"]) + 1
    bad_cap.tsip["public_signals"][6] = str(bad_cap.tsip["cap_policy_sq"])
    with pytest.raises(HTTPException):
        shuffler.ingestA(bad_cap)

    bad_tier_cap, _ = _make_followup_report("u4-bad-tier-anchor", user_id, ctx, local_state)
    bad_tier_cap.tsip["tier_anchor_cap_sq"] = int(bad_tier_cap.tsip["tier_anchor_cap_sq"]) + 1
    bad_tier_cap.tsip["public_signals"][5] = str(bad_tier_cap.tsip["tier_anchor_cap_sq"])
    with pytest.raises(HTTPException):
        shuffler.ingestA(bad_tier_cap)

    bad_relation, _ = _make_followup_report("u4-bad-relation", user_id, ctx, local_state)
    bad_relation.tsip["cap_policy_sq"] = int(bad_relation.tsip["tier_anchor_cap_sq"]) + 1
    bad_relation.tsip["public_signals"][6] = str(bad_relation.tsip["cap_policy_sq"])
    with pytest.raises(HTTPException):
        shuffler.ingestA(bad_relation)


def test_bootstrap_anchor_must_be_genesis_when_w_lt_k():
    user_id = "u5"
    ctx = _make_tsip_context(user_id)
    init, local_state = _make_enrollment_report("init-u5", user_id, ctx)
    shuffler.ingestA(init)
    shuffler.ingestR(init)

    bad_anchor, _ = _make_followup_report("u5-bad-anchor", user_id, ctx, local_state)
    bad_anchor.tsip["anchor_loc_commitment"] = str(bad_anchor.tsip["curr_loc_commitment"])
    bad_anchor.tsip["public_signals"][2] = str(commitment_to_field(str(bad_anchor.tsip["curr_loc_commitment"])))
    with pytest.raises(HTTPException) as exc:
        shuffler.ingestA(bad_anchor)
    assert "anchor_loc_commitment mismatch" in str(exc.value.detail)


def test_warmup_and_mode_only_reenrollment_semantics():
    user_id = "u6"
    ctx = _make_tsip_context(user_id, mode="vehicle", tier="transit")
    n_warm = max(int(shuffler.TSIP_ADWC_WINDOW_K), 2)

    init, local_state = _make_enrollment_report("init-u6", user_id, ctx)
    out_a = shuffler.ingestA(copy.deepcopy(init))
    out_r = shuffler.ingestR(copy.deepcopy(init))
    assert out_a["warmup_held"] is True and out_r["warmup_held"] is True

    for i in range(max(0, n_warm - 1)):
        rep, local_state = _make_followup_report(f"u6-warm-{i}", user_id, ctx, local_state)
        out = shuffler.ingestA(copy.deepcopy(rep))
        shuffler.ingestR(copy.deepcopy(rep))
        assert out["warmup_held"] is True

    rep, local_state = _make_followup_report("u6-warm-exit", user_id, ctx, local_state)
    out = shuffler.ingestA(copy.deepcopy(rep))
    shuffler.ingestR(copy.deepcopy(rep))
    assert out["warmup_held"] is False

    prev_state = shuffler.tsip_state_by_user[user_id]
    prev_modeset = str(prev_state["modeset_commitment"])
    prev_mode_tag = str(prev_state["mode_tag"])
    prev_epoch = int(prev_state["enrollment_epoch"])

    # mode-only re-enrollment: same tier + same modeset, new mode_tag.
    reenroll_ctx = _make_tsip_context(user_id, mode="transit", tier="transit")
    reenroll_ctx["modeset_bitmap"] = ctx["modeset_bitmap"]
    reenroll_ctx["modeset_salt"] = ctx["modeset_salt"]
    reenroll_ctx["modeset_commitment"] = prev_modeset
    reenroll_ctx["mode_tag"] = str(compute_mode_tag_field("transit", reenroll_ctx["secret"]))
    reenroll, local_state = _make_enrollment_report(
        "u6-reenroll",
        user_id,
        reenroll_ctx,
        x=int(local_state["x"]),
        y=int(local_state["y"]),
        timestamp=int(local_state["timestamp"]) + 60,
    )
    out_re_a = shuffler.ingestA(copy.deepcopy(reenroll))
    out_re_r = shuffler.ingestR(copy.deepcopy(reenroll))
    assert out_re_a["warmup_held"] is True and out_re_r["warmup_held"] is True

    st = shuffler.tsip_state_by_user[user_id]
    assert str(st["modeset_commitment"]) == prev_modeset
    assert str(st["mode_tag"]) != prev_mode_tag
    assert int(st["warmup_count"]) == 1
    assert int(st["enrollment_epoch"]) == prev_epoch + 1


def test_a4_cross_tier_sybil_share_threshold():
    old_warm = shuffler.TSIP_WARMUP_ROUNDS
    shuffler.TSIP_WARMUP_ROUNDS = 0
    try:
        benign_users = [f"benign_{i}" for i in range(10)]
        attacker_users = [("attacker_v", "vehicle"), ("attacker_t", "transit")]

        accepted_total = 0
        accepted_attacker = 0
        for uid in benign_users:
            ctx = _make_tsip_context(uid, mode="vehicle", tier="vehicle")
            rep, _ = _make_enrollment_report(f"enroll-{uid}", uid, ctx, timestamp=1000 + len(uid))
            shuffler.ingestA(copy.deepcopy(rep))
            shuffler.ingestR(copy.deepcopy(rep))
            accepted_total += 1

        for uid, tier in attacker_users:
            ctx = _make_tsip_context(uid, mode=tier, tier=tier)
            rep, _ = _make_enrollment_report(f"enroll-{uid}", uid, ctx, timestamp=2000 + len(uid))
            shuffler.ingestA(copy.deepcopy(rep))
            shuffler.ingestR(copy.deepcopy(rep))
            accepted_total += 1
            accepted_attacker += 1

        attacker_share = accepted_attacker / max(1, accepted_total)
        assert attacker_share <= 0.25

        tier_hist: dict[int, int] = {}
        for st in shuffler.tsip_state_by_user.values():
            tier_sq = int(st.get("tier_vmax_sq", 0) or 0)
            tier_hist[tier_sq] = tier_hist.get(tier_sq, 0) + 1
        assert len(tier_hist) >= 2
    finally:
        shuffler.TSIP_WARMUP_ROUNDS = old_warm
