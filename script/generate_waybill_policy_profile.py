#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.policy_profile import PolicyProfile, sha256_file  # noqa: E402
from common.settlement import (  # noqa: E402
    SETTLEMENT_CAP_POLICY_SQ,
    SETTLEMENT_POSITION_VALIDITY_RULE,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    TariffTable,
    canonical_json,
)


DEFAULT_OUTPUT_DIR = ROOT_DIR / "configs" / "settlement_policy_profiles"
DEFAULT_VKEY = ROOT_DIR / "zk" / "settlement_period_v6_k6" / "verification_key.json"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_v6_tariff() -> TariffTable:
    return TariffTable(
        tariff_version=9,
        grid_w=100,
        cell_zones={idx: (10 if idx < 128 else 20) for idx in range(1 << 8)},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def profile_schema() -> dict[str, object]:
    integer_fields = [
        "profile_version",
        "valid_from",
        "valid_to",
        "min_accepted_version",
        "tariff_version",
        "tariff_root",
        "tariff_tree_depth",
        "max_fixes",
        "max_zone_rate_cents_per_m",
        "cadence_sec",
        "max_dt_sec",
        "tier_vmax_mps",
        "tier_vmax_sq",
        "mode_vmax_sq",
        "cap_policy_sq",
        "fixed_point_scale",
        "monthly_reconciliation_rate_cents_per_m",
    ]
    string_fields = [
        "authority_id",
        "jurisdiction_id",
        "cap_policy_hash",
        "circuit_id",
        "verification_key_hash",
        "currency",
        "rounding_mode",
        "overflow_policy",
        "fallback_semantics_version",
        "receiver_attestation_schema",
        "position_validity_rule",
        "verification_key_path",
        "tariff_artifact_path",
    ]
    properties: dict[str, object] = {
        "domain_sep": {"const": "waybill_policy_profile_v1"},
        "commitment_version": {"const": 1},
        "revoked_at": {"type": ["integer", "null"], "minimum": 0},
        "policy_profile_commitment": {"type": "string", "pattern": "^[0-9]+$"},
        "profile_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }
    properties.update({name: {"type": "integer", "minimum": 1} for name in integer_fields})
    properties.update({name: {"type": "string", "minLength": 1} for name in string_fields})
    v6_only = {"receiver_attestation_schema", "position_validity_rule"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://waybill.example/schema/policy-profile-v1.json",
        "title": "WayBill Canonical PolicyProfile v1",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(set(properties) - v6_only),
        "properties": properties,
        "allOf": [
            {
                "if": {
                    "properties": {
                        "circuit_id": {"pattern": "^settlement-period-v6-"}
                    },
                    "required": ["circuit_id"],
                },
                "then": {
                    "required": sorted(v6_only),
                    "properties": {
                        "receiver_attestation_schema": {
                            "const": SETTLEMENT_ROOT_ATTESTATION_SCHEMA
                        },
                        "position_validity_rule": {
                            "const": SETTLEMENT_POSITION_VALIDITY_RULE
                        },
                    },
                },
            }
        ],
    }


def generate(output_dir: Path, vkey_path: Path) -> dict[str, str]:
    if not vkey_path.is_file():
        raise FileNotFoundError(f"verification key not found: {vkey_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    tariff = build_v6_tariff()
    tariff_name = "ruc-demo-tariff-v9-d8.json"
    tariff_payload = {
        "type": "tariff-artifact",
        "artifact_version": 1,
        "tariff_version": tariff.tariff_version,
        "grid_w": tariff.grid_w,
        "tree_depth": 8,
        "leaf_ordering": "ascending-cell-index",
        "padding_rule": "repeat-last-leaf",
        "hash_domain": "poseidon2-tariff-leaf-v6",
        "cell_zones": {str(key): value for key, value in sorted(tariff.cell_zones.items())},
        "zone_rates_cents_per_m": {
            str(key): value for key, value in sorted(tariff.zone_rates_cents_per_m.items())
        },
        "tariff_root": str(tariff.root(8)),
        "max_zone_rate_cents_per_m": tariff.max_zone_rate_cents_per_m,
    }
    _write_json(output_dir / tariff_name, tariff_payload)

    cap_policy_hash = hashlib.sha256(
        canonical_json(
            {"domain_sep": "waybill_cap_policy_v1", "cap_policy_sq": SETTLEMENT_CAP_POLICY_SQ}
        ).encode("utf-8")
    ).hexdigest()
    try:
        relative_vkey = str(vkey_path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        relative_vkey = str(Path("../..") / vkey_path.resolve().relative_to(ROOT_DIR.resolve()))
    # relative_to() cannot express parent traversal.  Keep the repository-local
    # path deterministic for the default artifact and absolute paths otherwise.
    if vkey_path.resolve().is_relative_to(ROOT_DIR.resolve()):
        relative_vkey = str(Path("../..") / vkey_path.resolve().relative_to(ROOT_DIR.resolve()))

    profile = PolicyProfile(
        authority_id="ruc-demo-authority",
        jurisdiction_id="ruc-demo",
        profile_version=9,
        valid_from=1_777_593_600,
        valid_to=1_798_761_600,
        revoked_at=None,
        min_accepted_version=9,
        tariff_version=9,
        tariff_root=tariff.root(8),
        tariff_tree_depth=8,
        max_fixes=25,
        max_zone_rate_cents_per_m=tariff.max_zone_rate_cents_per_m,
        cadence_sec=300,
        max_dt_sec=600,
        tier_vmax_mps=33,
        tier_vmax_sq=33 * 33,
        mode_vmax_sq=33 * 33,
        cap_policy_sq=SETTLEMENT_CAP_POLICY_SQ,
        cap_policy_hash=cap_policy_hash,
        circuit_id="settlement-period-v6-validity-bound-k25-d8",
        verification_key_hash=sha256_file(vkey_path),
        currency="EUR",
        fixed_point_scale=1,
        rounding_mode="exact-integer",
        overflow_policy="reject-u96",
        monthly_reconciliation_rate_cents_per_m=tariff.max_zone_rate_cents_per_m,
        fallback_semantics_version="odometer-max-rate-v6",
        receiver_attestation_schema=SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
        position_validity_rule=SETTLEMENT_POSITION_VALIDITY_RULE,
        verification_key_path=relative_vkey,
        tariff_artifact_path=tariff_name,
    )
    profile_path = output_dir / "ruc-demo-v9.json"
    _write_json(profile_path, profile.to_dict())
    _write_json(output_dir / "policy-profile-v1.schema.json", profile_schema())
    _write_json(
        output_dir / "policy-profile-v1-test-vectors.json",
        {
            "domain_sep": "waybill_policy_profile_test_vectors_v1",
            "vectors": [
                {
                    "name": "ruc-demo-v9",
                    "canonical_serialization": profile.canonical_serialization,
                    "profile_sha256": profile.profile_sha256,
                    "policy_profile_commitment": str(profile.commitment),
                }
            ],
        },
    )
    return {
        "profile": str(profile_path),
        "tariff": str(output_dir / tariff_name),
        "schema": str(output_dir / "policy-profile-v1.schema.json"),
        "vectors": str(output_dir / "policy-profile-v1-test-vectors.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the canonical WayBill M0 demo profile.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--vkey", type=Path, default=DEFAULT_VKEY)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir, args.vkey), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
