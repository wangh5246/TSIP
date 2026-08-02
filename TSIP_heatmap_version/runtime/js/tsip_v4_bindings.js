"use strict";

const { buildPoseidon } = require("circomlibjs");

const DOMAIN_LOCATION = "13438772816005774064980671497565679151312422504895540615973695163839855496153";

const PUBLIC_SIGNAL_ORDER = [
  "hash_prev",
  "hash_curr",
  "hash_anchor",
  "step_dt_sq",
  "tier_vmax_sq",
  "tier_anchor_cap_sq",
  "cap_policy_sq",
  "primary_commitment",
  "payload_commitment_v2",
  "share_content_commitment_a",
  "share_content_commitment_r",
  "secret_commitment",
  "modeset_commitment",
  "mode_tag",
];

const PAPER_PUBLIC_SIGNAL_ORDER = [
  "hash_prev",
  "hash_curr",
  "hash_anchor",
  "step_dt_sq",
  "tier_vmax_sq",
  "tier_anchor_cap_sq",
  "cap_policy_sq",
  "primary_commitment",
  "payload_commitment_v2",
  "share_content_commitment_a",
  "share_content_commitment_r",
  "context_commitment",
  "blob_hash",
  "secret_commitment",
  "modeset_commitment",
  "mode_tag",
];

async function poseidonHash(values) {
  const poseidon = await buildPoseidon();
  const F = poseidon.F;
  return F.toObject(poseidon(values.map((v) => BigInt(v)))).toString();
}

async function poseidonChain(domain, values) {
  let state = BigInt(domain);
  for (const value of values) {
    state = BigInt(await poseidonHash([state, value]));
  }
  return state.toString();
}

async function deriveV4WitnessFields(input) {
  const out = { ...input };
  out.hash_prev = await poseidonHash([out.x1, out.y1, out.r_prev]);
  out.hash_curr = await poseidonHash([out.x2, out.y2, out.r_curr]);
  out.hash_anchor = await poseidonHash([out.x_anchor, out.y_anchor, out.r_anchor]);
  out.payload_primary_idx = String(BigInt(out.payload_cell_y) * 100n + BigInt(out.payload_cell_x));
  out.primary_commitment = await poseidonHash([out.payload_primary_idx, out.primary_salt]);
  out.payload_commitment_v2 = await poseidonHash([
    out.primary_commitment,
    out.share_content_commitment_a,
    out.share_content_commitment_r,
  ]);
  out.secret_commitment = await poseidonHash([out.secret, out.user_id_field]);
  out.modeset_commitment = await poseidonHash([out.modeset_bitmap, out.modeset_salt]);
  const modeId =
    BigInt(out.mode_s1 || 0) + 2n * BigInt(out.mode_s2 || 0) + 3n * BigInt(out.mode_s3 || 0);
  out.mode_tag = await poseidonHash([modeId.toString(), out.secret]);
  return out;
}

async function deriveV4PaperWitnessFields(input) {
  const out = { ...input };
  out.hash_prev = await poseidonChain(DOMAIN_LOCATION, [out.x1, out.y1, out.r_prev]);
  out.hash_curr = await poseidonChain(DOMAIN_LOCATION, [out.x2, out.y2, out.r_curr]);
  out.hash_anchor = await poseidonChain(DOMAIN_LOCATION, [out.x_anchor, out.y_anchor, out.r_anchor]);
  out.payload_primary_idx = String(BigInt(out.payload_cell_y) * 100n + BigInt(out.payload_cell_x));
  out.primary_commitment = await poseidonHash([out.payload_primary_idx, out.primary_salt]);
  out.share_content_commitment_a = await poseidonHash([
    out.primary_commitment,
    out.share_digest_a,
    out.context_commitment,
  ]);
  out.share_content_commitment_r = await poseidonHash([
    out.primary_commitment,
    out.share_digest_r,
    out.context_commitment,
  ]);
  out.payload_commitment_v2 = await poseidonHash([
    out.primary_commitment,
    out.share_content_commitment_a,
    out.share_content_commitment_r,
  ]);
  out.blob_hash = await poseidonHash([
    out.payload_primary_idx,
    out.share_content_commitment_a,
    out.share_content_commitment_r,
    out.context_commitment,
  ]);
  out.secret_commitment = await poseidonHash([out.secret, out.user_id_field]);
  out.modeset_commitment = await poseidonHash([out.modeset_bitmap, out.modeset_salt]);
  const modeId =
    BigInt(out.mode_s1 || 0) + 2n * BigInt(out.mode_s2 || 0) + 3n * BigInt(out.mode_s3 || 0);
  out.mode_tag = await poseidonHash([modeId.toString(), out.secret]);
  return out;
}

function publicSignalsFromInput(input) {
  return PUBLIC_SIGNAL_ORDER.map((key) => String(input[key]));
}

function publicSignalsFromPaperInput(input) {
  return PAPER_PUBLIC_SIGNAL_ORDER.map((key) => String(input[key]));
}

function verifySignals(publicSignals, expected, order) {
  if (!Array.isArray(publicSignals) || publicSignals.length !== order.length) {
    return { ok: false, error: `expected ${order.length} public signals` };
  }
  for (let i = 0; i < order.length; i += 1) {
    const key = order[i];
    if (String(publicSignals[i]) !== String(expected[key])) {
      return { ok: false, error: `public signal ${i} ${key} mismatch` };
    }
  }
  return { ok: true, error: "" };
}

function verifyPublicSignals(publicSignals, expected) {
  return verifySignals(publicSignals, expected, PUBLIC_SIGNAL_ORDER);
}

function verifyPaperPublicSignals(publicSignals, expected) {
  return verifySignals(publicSignals, expected, PAPER_PUBLIC_SIGNAL_ORDER);
}

module.exports = {
  PUBLIC_SIGNAL_ORDER,
  PAPER_PUBLIC_SIGNAL_ORDER,
  DOMAIN_LOCATION,
  deriveV4WitnessFields,
  deriveV4PaperWitnessFields,
  publicSignalsFromInput,
  publicSignalsFromPaperInput,
  verifyPublicSignals,
  verifyPaperPublicSignals,
};
