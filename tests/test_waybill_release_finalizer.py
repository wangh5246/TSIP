from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from types import SimpleNamespace
from typing import Any

import pytest

from common.policy_profile import PolicyProfile
from common.settlement import (
    SETTLEMENT_POSITION_VALIDITY_RULE,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    TariffTable,
)
from common.settlement_v6 import PUBLIC_SIGNAL_ORDER_V6

SCRIPT = Path(__file__).parents[1] / "script" / "finalize_waybill_release.py"
SPEC = importlib.util.spec_from_file_location("finalize_waybill_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

ReleaseError = MODULE.ReleaseError
_profile_semantic_sha256 = MODULE._profile_semantic_sha256
_release_assets = MODULE._release_assets
build_code_manifest = MODULE.build_code_manifest
build_prover_manifest = MODULE.build_prover_manifest
build_release = MODULE.build_release
bind_scanner_sbom = MODULE.bind_scanner_sbom
bind_scanner_vulnerability_report = MODULE.bind_scanner_vulnerability_report
canonical_sha256 = MODULE.canonical_sha256
create_image_metadata = MODULE.create_image_metadata
create_source_bundle = MODULE.create_source_bundle
git_release_identity = MODULE.git_release_identity
sha256_bytes = MODULE.sha256_bytes
sha256_file = MODULE.sha256_file
verify_image_metadata = MODULE.verify_image_metadata
verify_formal_runner_embedded_source = MODULE.verify_formal_runner_embedded_source
verify_profile_and_receipts = MODULE.verify_profile_and_receipts
verify_prover_archive = MODULE.verify_prover_archive
verify_release = MODULE.verify_release
verify_release_blockers = MODULE.verify_release_blockers
verify_release_inventory = MODULE.verify_release_inventory
verify_sbom = MODULE.verify_sbom
verify_vulnerability_report = MODULE.verify_vulnerability_report
verify_source_bundle = MODULE.verify_source_bundle
verify_tagged_config = MODULE.verify_tagged_config
write_canonical_json = MODULE.write_canonical_json
write_deterministic_tar = MODULE.write_deterministic_tar
write_sha256sums = MODULE.write_sha256sums


@pytest.fixture(autouse=True)
def _strict_groth16_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    def verify(vkey_blob: bytes, public_blob: bytes, proof_blob: bytes) -> None:
        vkey = json.loads(vkey_blob)
        public = json.loads(public_blob)
        proof = json.loads(proof_blob)
        assert vkey.get("protocol") == "groth16"
        assert isinstance(public, list) and all(isinstance(item, str) for item in public)
        assert isinstance(proof, dict) and isinstance(proof.get("pi_a"), list)

    monkeypatch.setattr(MODULE, "_run_groth16_verify", verify)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_image_tar(
    path: Path,
    role: str,
    bindings: dict[str, str],
    *,
    formal_source: bytes = b"VALUE = 'tagged'\n",
) -> dict[str, str]:
    layer_buffer = io.BytesIO()
    with tarfile.open(fileobj=layer_buffer, mode="w") as layer_archive:
        if role == "formal-runner":
            source = formal_source
            source_info = tarfile.TarInfo("work/src/app.py")
            source_info.mode = 0o644
            source_info.size = len(source)
            layer_archive.addfile(source_info, io.BytesIO(source))
            embedded = json.dumps(
                {
                    "schema": "waybill.formal.embedded-release-binding/v1",
                    **bindings,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode() + b"\n"
            binding_info = tarfile.TarInfo("opt/waybill/release-bindings.json")
            binding_info.mode = 0o444
            binding_info.size = len(embedded)
            layer_archive.addfile(binding_info, io.BytesIO(embedded))
    layer = layer_buffer.getvalue()
    users = {
        "formal-runner": "10003:10003",
        "charger": "10002:10002",
        "postgres": "70:70",
        "receiver-signer": "10001:10001",
    }
    labels = {
        label: bindings[binding_key]
        for label, binding_key in MODULE.CONTAINER_BINDING_LABELS.items()
    }
    config = {
        "architecture": "amd64",
        "os": "linux",
        "config": {"Labels": labels, "User": users[role]},
        "rootfs": {"type": "layers", "diff_ids": ["sha256:" + hashlib.sha256(layer).hexdigest()]},
    }
    config_blob = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    config_digest = hashlib.sha256(config_blob).hexdigest()
    config_name = f"{config_digest}.json"
    image_ref = f"waybill/{role}:test"
    records = {
        "manifest.json": json.dumps(
            [
                {
                    "Config": config_name,
                    "RepoTags": [image_ref],
                    "Layers": ["layer.tar"],
                }
            ]
        ).encode(),
        config_name: config_blob,
        "layer.tar": layer,
    }
    with tarfile.open(path, "w") as archive:
        for name, data in records.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return {
        "archive_format": "docker-save",
        "config_digest": f"sha256:{config_digest}",
        "image_digest": f"sha256:{config_digest}",
        "image_ref": image_ref,
        "user": users[role],
    }


def _write_oci_docker_save_tar(
    path: Path, role: str, bindings: dict[str, str]
) -> dict[str, str]:
    users = {
        "formal-runner": "10003:10003",
        "charger": "10002:10002",
        "postgres": "70:70",
        "receiver-signer": "10001:10001",
    }
    image_ref = f"waybill/{role}:test"
    layer = b"fixture-oci-layer"
    layer_hash = hashlib.sha256(layer).hexdigest()
    labels = {
        label: bindings[binding_key]
        for label, binding_key in MODULE.CONTAINER_BINDING_LABELS.items()
    }
    config = {
        "architecture": "amd64",
        "os": "linux",
        "config": {"Labels": labels, "User": users[role]},
        "rootfs": {"type": "layers", "diff_ids": ["sha256:" + layer_hash]},
    }
    config_blob = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    config_hash = hashlib.sha256(config_blob).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "digest": "sha256:" + config_hash,
            "size": len(config_blob),
        },
        "layers": [
            {
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                "digest": "sha256:" + layer_hash,
                "size": len(layer),
            }
        ],
    }
    manifest_blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_hash = hashlib.sha256(manifest_blob).hexdigest()
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "digest": "sha256:" + manifest_hash,
                "size": len(manifest_blob),
                "annotations": {
                    "io.containerd.image.name": f"docker.io/library/{image_ref}",
                    "org.opencontainers.image.ref.name": "test",
                },
            }
        ],
    }
    docker_manifest = [
        {
            "Config": f"blobs/sha256/{config_hash}",
            "RepoTags": [image_ref],
            "Layers": [f"blobs/sha256/{layer_hash}"],
        }
    ]
    records = {
        "blobs/sha256/" + config_hash: config_blob,
        "blobs/sha256/" + layer_hash: layer,
        "blobs/sha256/" + manifest_hash: manifest_blob,
        "index.json": json.dumps(index).encode(),
        "manifest.json": json.dumps(docker_manifest).encode(),
        "oci-layout": json.dumps({"imageLayoutVersion": "1.0.0"}).encode(),
    }
    with tarfile.open(path, "w") as archive:
        for name, data in records.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return {
        "archive_format": "oci-layout",
        "config_digest": "sha256:" + config_hash,
        "image_digest": "sha256:" + manifest_hash,
        "image_ref": image_ref,
        "user": users[role],
    }


def _write_sbom(
    path: Path,
    *,
    role: str,
    metadata: dict[str, Any],
    bindings: dict[str, str],
) -> None:
    package_id = "SPDXRef-Package"
    _write_json(
        path,
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "dataLicense": "CC0-1.0",
            "name": f"waybill-{role}",
            "documentNamespace": f"https://waybill.example.test/spdx/{role}",
            "creationInfo": {
                "created": "2026-07-29T00:00:00Z",
                "creators": ["Tool: waybill-release-test-fixture"],
            },
            "documentDescribes": [package_id],
            "packages": [{"name": role, "SPDXID": package_id}],
            "waybillBinding": {
                "role": role,
                "image_digest": metadata["image_digest"],
                "image_tar_sha256": metadata["image_tar_sha256"],
                **bindings,
            },
        },
    )


def _write_vulnerability_report(
    path: Path,
    *,
    role: str,
    metadata: dict[str, Any],
    bindings: dict[str, str],
    vulnerabilities: list[dict[str, Any]] | None = None,
) -> None:
    findings = vulnerabilities or []
    fixable_by_severity = {
        severity: sum(
            item["Severity"] == severity and bool(item.get("FixedVersion", ""))
            for item in findings
        )
        for severity in ("CRITICAL", "HIGH", "LOW", "MEDIUM", "UNKNOWN")
    }
    summary = {
        "critical": sum(item["Severity"] == "CRITICAL" for item in findings),
        "fixable_by_severity": fixable_by_severity,
        "fixable_high_critical": sum(
            item["Severity"] in {"HIGH", "CRITICAL"}
            and bool(item.get("FixedVersion", ""))
            for item in findings
        ),
        "fixable_total": sum(fixable_by_severity.values()),
        "high": sum(item["Severity"] == "HIGH" for item in findings),
        "total_high_critical": sum(
            item["Severity"] in {"HIGH", "CRITICAL"} for item in findings
        ),
        "unfixed_high_critical_ids": sorted(
            {
                item["VulnerabilityID"]
                for item in findings
                if item["Severity"] in {"HIGH", "CRITICAL"}
                and not item.get("FixedVersion", "")
            }
        ),
    }
    scanner = {
        "name": "trivy",
        "report_schema_version": 2,
        "version": "0.72.0",
    }
    _write_json(
        path,
        {
            "SchemaVersion": 2,
            "Trivy": {"Version": "0.72.0"},
            "ReportID": f"test-report-{role}",
            "CreatedAt": "2026-07-29T00:00:00Z",
            "ArtifactID": "sha256:" + "e" * 64,
            "ArtifactName": metadata["image_ref"],
            "ArtifactType": "container_image",
            "Metadata": {
                "ImageID": metadata["image_digest"],
                "Reference": metadata["image_ref"],
                "RepoTags": [metadata["image_ref"]],
            },
            "Results": [
                {
                    "Target": metadata["image_ref"],
                    "Class": "os-pkgs",
                    "Type": "fixture",
                    "Vulnerabilities": findings,
                }
            ],
            "waybillBinding": {
                "role": role,
                "image_digest": metadata["image_digest"],
                "image_tar_sha256": metadata["image_tar_sha256"],
                "scan_image_id": metadata["image_digest"],
                "scanner": scanner,
                "summary": summary,
                **bindings,
            },
        },
    )


def _make_tagged_repo(tmp_path: Path, *, lfs_app: bool = False) -> tuple[Path, dict[str, Any]]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(("git", "init", "--quiet", str(repo)), check=True)
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release@example.test")

    app = repo / "src/app.py"
    app.parent.mkdir(parents=True)
    if lfs_app:
        app.write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:" + "a" * 64 + "\nsize 9\n",
            encoding="utf-8",
        )
    else:
        app.write_text("VALUE = 'tagged'\n", encoding="utf-8")
    (repo / ".gitignore").write_text("/prover/\n", encoding="utf-8")
    prover_file = repo / "prover/circuit.r1cs"
    prover_file.parent.mkdir()
    prover_file.write_bytes(b"test prover r1cs")
    vkey = repo / "zk/verification_key.json"
    _write_json(vkey, {"protocol": "groth16", "curve": "bn128"})
    tariff = repo / "configs/tariff.json"
    tariff_table = TariffTable(
        tariff_version=9,
        grid_w=2,
        cell_zones={0: 10, 1: 10, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )
    tariff_root = tariff_table.root(2)
    _write_json(
        tariff,
        {
            "tariff_version": 9,
            "grid_w": 2,
            "cell_zones": {str(key): value for key, value in tariff_table.cell_zones.items()},
            "zone_rates_cents_per_m": {
                str(key): value for key, value in tariff_table.zone_rates_cents_per_m.items()
            },
            "tree_depth": 2,
            "tariff_root": str(tariff_root),
            "max_zone_rate_cents_per_m": 5,
        },
    )
    proof = repo / "evidence/proof.json"
    public = repo / "evidence/public.json"
    submission = repo / "evidence/submission.json"
    _write_json(proof, {"pi_a": ["1", "2"]})
    profile_model = PolicyProfile(
        authority_id="test-authority",
        jurisdiction_id="test",
        profile_version=9,
        valid_from=1,
        valid_to=10_000,
        revoked_at=None,
        min_accepted_version=9,
        tariff_version=9,
        tariff_root=tariff_root,
        tariff_tree_depth=2,
        max_fixes=25,
        max_zone_rate_cents_per_m=5,
        cadence_sec=300,
        max_dt_sec=600,
        tier_vmax_mps=33,
        tier_vmax_sq=1089,
        mode_vmax_sq=1089,
        cap_policy_sq=3_000_000_000,
        cap_policy_hash="a" * 64,
        circuit_id="settlement-period-v6-test",
        verification_key_hash=_sha(vkey),
        currency="EUR",
        fixed_point_scale=1,
        rounding_mode="exact-integer",
        overflow_policy="reject-u96",
        monthly_reconciliation_rate_cents_per_m=5,
        fallback_semantics_version="odometer-max-rate-v6",
        verification_key_path="../zk/verification_key.json",
        tariff_artifact_path="tariff.json",
        receiver_attestation_schema=SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
        position_validity_rule=SETTLEMENT_POSITION_VALIDITY_RULE,
    )
    public_by_name = {name: "1" for name in PUBLIC_SIGNAL_ORDER_V6}
    public_by_name.update(
        {
            "tariff_root": str(profile_model.tariff_root),
            "policy_profile_commitment": str(profile_model.commitment),
            "tariff_version": str(profile_model.tariff_version),
            "cadence_sec": str(profile_model.cadence_sec),
            "tier_vmax_mps": str(profile_model.tier_vmax_mps),
            "tier_vmax_sq": str(profile_model.tier_vmax_sq),
            "mode_vmax_sq": str(profile_model.mode_vmax_sq),
            "cap_policy_sq": str(profile_model.cap_policy_sq),
            "max_zone_rate_cents_per_m": str(profile_model.max_zone_rate_cents_per_m),
            "max_dt_sec": str(profile_model.max_dt_sec),
        }
    )
    public_signals = [public_by_name[name] for name in PUBLIC_SIGNAL_ORDER_V6]
    _write_json(public, public_signals)
    _write_json(submission, {"proof": "proof.json", "public": "public.json"})

    profile: dict[str, Any] = profile_model.to_dict()
    profile_path = repo / "configs/profile.json"
    _write_json(profile_path, profile)

    artifact_paths = {
        "proof.json": "evidence/proof.json",
        "public.json": "evidence/public.json",
        "submission.json": "evidence/submission.json",
        "verification_key.json": "zk/verification_key.json",
    }
    endpoint = {
        "schema": "test-endpoint-receipt-v2",
        "status": "verified",
        "hard_gate_passed": True,
        "gates": {"proof_verified": True},
        "accepted": {"policy_profile_commitment": str(profile_model.commitment)},
        "code_sha256": {"src/app.py": _sha(app)},
        "artifact_sha256": {
            name: _sha(repo / path) for name, path in artifact_paths.items()
        },
        "policy_artifact_sha256": {
            "profile.json": _sha(profile_path),
            "tariff.json": _sha(tariff),
        },
    }
    circuit = {
        "schema": "test-circuit-receipt-v2",
        "ok": True,
        "canonical_profile_bound": True,
        "circuit_python_differential_match": True,
        "receiver_attestation_sha256": "a" * 64,
        "previous_attestation_sha256": "0" * 64,
        "public_signal_order": list(PUBLIC_SIGNAL_ORDER_V6),
        "public_signals": public_signals,
        "python_reference_public_signals": public_signals,
        "code_sha256": {"src/app.py": _sha(app)},
        "policy_profile_sha256": profile["profile_sha256"],
        "policy_profile_commitment": profile["policy_profile_commitment"],
        "artifact_sha256": {
            "proof_json": _sha(proof),
            "public_json": _sha(public),
            "verification_key": _sha(vkey),
            "r1cs": _sha(prover_file),
        },
    }
    endpoint_path = repo / "evidence/endpoint-receipt.json"
    circuit_path = repo / "evidence/circuit-receipt.json"
    _write_json(endpoint_path, endpoint)
    _write_json(circuit_path, circuit)
    _write_json(repo / "config/protocol.json", {"schema": "protocol/v1", "threshold": 5})

    config: dict[str, Any] = {
        "schema": "waybill-release-finalizer-config/v2",
        "release_name": "test-release",
        "config_path": "config/release.json",
        "protocol_path": "config/protocol.json",
        "code_manifest": {
            "required_paths": [
                "src/app.py",
                "configs/profile.json",
                "configs/tariff.json",
                "zk/verification_key.json",
                "evidence/endpoint-receipt.json",
                "evidence/circuit-receipt.json",
                "evidence/proof.json",
                "evidence/public.json",
                "evidence/submission.json",
                "config/protocol.json",
                "config/release.json",
            ],
            "scopes": ["src", "configs", "zk", "evidence", "config"],
        },
        "bindings": {
            "profile": "configs/profile.json",
            "endpoint_receipt": "evidence/endpoint-receipt.json",
            "circuit_receipt": "evidence/circuit-receipt.json",
            "endpoint_code": {"src/app.py": "src/app.py"},
            "circuit_code": {"src/app.py": "src/app.py"},
            "endpoint_artifacts": artifact_paths,
            "endpoint_policy_artifacts": {
                "profile.json": "configs/profile.json",
                "tariff.json": "configs/tariff.json",
            },
            "circuit_artifacts": {
                "proof_json": "evidence/proof.json",
                "public_json": "evidence/public.json",
                "verification_key": "zk/verification_key.json",
            },
        },
        "prover": {
            "directory": "prover",
            "files": {"r1cs": "circuit.r1cs"},
            "allowed_extra": [],
        },
        "containers": {
            "scanner": {
                "name": "trivy",
                "report_schema_version": 2,
                "version": "0.72.0",
            },
            "roles": {
                "formal-runner": {
                    "embedded_source_paths": ["src"],
                    "platform": "linux/amd64",
                    "user": "10003:10003",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
                "charger": {
                    "platform": "linux/amd64",
                    "user": "10002:10002",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
                "postgres": {
                    "platform": "linux/amd64",
                    "user": "70:70",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
                "receiver-signer": {
                    "platform": "linux/amd64",
                    "user": "10001:10001",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
            }
        },
        "receipt_requirements": {
            "endpoint_schema": "test-endpoint-receipt-v2",
            "circuit_schema": "test-circuit-receipt-v2",
            "endpoint": {"status": "verified", "hard_gate_passed": True},
            "circuit": {
                "ok": True,
                "canonical_profile_bound": True,
                "circuit_python_differential_match": True,
            },
            "endpoint_gates": ["proof_verified"],
        },
        "tag_assets": {"evidence/proof.json": "evidence/proof.json"},
    }
    _write_json(repo / "config/release.json", config)
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "release fixture")
    _git(repo, "tag", "-a", "release-v2", "-m", "formal release v2")
    return repo, config


def test_release_identity_requires_annotated_head_and_clean_tree(tmp_path: Path) -> None:
    repo, _ = _make_tagged_repo(tmp_path)
    identity = git_release_identity(repo, "release-v2")
    assert identity["commit"] == _git(repo, "rev-parse", "HEAD")
    assert identity["tree"] == _git(repo, "rev-parse", "HEAD^{tree}")

    _git(repo, "tag", "lightweight")
    with pytest.raises(ReleaseError, match="not an annotated tag"):
        git_release_identity(repo, "lightweight")

    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="not clean"):
        git_release_identity(repo, "release-v2")
    (repo / "untracked.txt").unlink()

    (repo / "next.txt").write_text("next\n", encoding="utf-8")
    _git(repo, "add", "next.txt")
    _git(repo, "commit", "--quiet", "-m", "post release")
    with pytest.raises(ReleaseError, match="is not HEAD"):
        git_release_identity(repo, "release-v2")


def test_release_blockers_fail_closed() -> None:
    verify_release_blockers({})
    with pytest.raises(ReleaseError, match="release is blocked"):
        verify_release_blockers({"release_blockers": ["pending upstream security release"]})


def test_code_manifest_reads_tag_blobs_not_worktree(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path)
    identity = git_release_identity(repo, "release-v2")
    tagged = (repo / "src/app.py").read_bytes()
    (repo / "src/app.py").write_text("VALUE = 'worktree-only'\n", encoding="utf-8")

    manifest = build_code_manifest(repo, "release-v2", config, identity=identity)
    records = {record["path"]: record for record in manifest["files"]}
    assert records["src/app.py"]["sha256"] == sha256_bytes(tagged)
    assert records["src/app.py"]["sha256"] != _sha(repo / "src/app.py")
    assert manifest["git_tree"] == identity["tree"]
    assert manifest["file_count"] == len(records)


def test_finalizer_config_must_match_its_tagged_blob(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path)
    assert verify_tagged_config(repo, "release-v2", config) == "config/release.json"
    changed = {**config, "release_name": "worktree-override"}
    with pytest.raises(ReleaseError, match="does not match the tagged config"):
        verify_tagged_config(repo, "release-v2", changed)


def test_required_path_and_lfs_pointer_are_rejected(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path / "missing")
    identity = git_release_identity(repo, "release-v2")
    config["code_manifest"]["required_paths"].append("missing.txt")
    with pytest.raises(ReleaseError, match="required tagged path is missing"):
        build_code_manifest(repo, "release-v2", config, identity=identity)

    lfs_repo, lfs_config = _make_tagged_repo(tmp_path / "lfs", lfs_app=True)
    lfs_identity = git_release_identity(lfs_repo, "release-v2")
    with pytest.raises(ReleaseError, match="LFS pointer"):
        build_code_manifest(lfs_repo, "release-v2", lfs_config, identity=lfs_identity)


def test_profile_vkey_and_receipt_code_hashes_are_bound_to_tag(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path)
    result = verify_profile_and_receipts(repo, "release-v2", config)
    assert result["verification_key_sha256"] == _sha(repo / "zk/verification_key.json")
    profile = json.loads((repo / "configs/profile.json").read_text(encoding="utf-8"))
    assert result["policy_profile_commitment"] == profile["policy_profile_commitment"]

    (repo / "src/app.py").write_text("VALUE = 'changed-after-receipt'\n", encoding="utf-8")
    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "--quiet", "-m", "stale receipt")
    _git(repo, "tag", "-a", "bad-v2", "-m", "bad release")
    with pytest.raises(ReleaseError, match="endpoint code hash mismatch"):
        verify_profile_and_receipts(repo, "bad-v2", config)


def test_profile_semantic_hash_is_checked_independently(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path)
    profile_path = repo / "configs/profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["authority_id"] = "tampered"
    _write_json(profile_path, profile)
    _git(repo, "add", "configs/profile.json")
    _git(repo, "commit", "--quiet", "-m", "tamper profile")
    _git(repo, "tag", "-a", "tampered-v2", "-m", "tampered release")
    with pytest.raises(ReleaseError, match="semantic SHA-256"):
        verify_profile_and_receipts(repo, "tampered-v2", config)


def test_prover_manifest_and_tar_are_deterministic_and_exact(tmp_path: Path) -> None:
    prover = tmp_path / "prover"
    (prover / "js").mkdir(parents=True)
    (prover / "circuit.r1cs").write_bytes(b"r1cs\x00fixture")
    (prover / "js/circuit.wasm").write_bytes(b"\x00asmfixture")
    (prover / "ignored.sym").write_text("symbols\n", encoding="utf-8")
    config = {
        "files": {"r1cs": "circuit.r1cs", "wasm": "js/circuit.wasm"},
        "allowed_extra": ["ignored.sym"],
    }
    bindings = {
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "code_manifest_sha256": "c" * 64,
        "protocol_sha256": "d" * 64,
    }
    receipt = {
        "r1cs": _sha(prover / "circuit.r1cs"),
        "wasm": _sha(prover / "js/circuit.wasm"),
    }
    manifest = build_prover_manifest(
        prover,
        config,
        bindings=bindings,
        receipt_artifact_sha256=receipt,
    )
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    write_deterministic_tar(first, prover, manifest, mtime=1_700_000_000)
    write_deterministic_tar(second, prover, manifest, mtime=1_700_000_000)
    assert first.read_bytes() == second.read_bytes()
    verified = verify_prover_archive(first, expected_bindings=bindings)
    assert verified == manifest

    with tarfile.open(tmp_path / "malicious.tar", "w") as archive:
        manifest_data = (json.dumps(manifest) + "\n").encode()
        manifest_info = tarfile.TarInfo("artifact-manifest.json")
        manifest_info.size = len(manifest_data)
        archive.addfile(manifest_info, io.BytesIO(manifest_data))
        bad_data = b"escape"
        bad_info = tarfile.TarInfo("../escape")
        bad_info.size = len(bad_data)
        archive.addfile(bad_info, io.BytesIO(bad_data))
    with pytest.raises(ReleaseError, match="unsafe tar member"):
        verify_prover_archive(tmp_path / "malicious.tar")


def test_prover_manifest_rejects_receipt_mismatch_and_unlisted_file(tmp_path: Path) -> None:
    prover = tmp_path / "prover"
    prover.mkdir()
    (prover / "circuit.r1cs").write_bytes(b"circuit")
    config = {"files": {"r1cs": "circuit.r1cs"}}
    with pytest.raises(ReleaseError, match="does not match receipt"):
        build_prover_manifest(
            prover,
            config,
            bindings={},
            receipt_artifact_sha256={"r1cs": "0" * 64},
        )
    (prover / "surprise.bin").write_bytes(b"surprise")
    with pytest.raises(ReleaseError, match="unexpected prover files"):
        build_prover_manifest(prover, config, bindings={})


def test_source_bundle_resolves_same_annotated_tag_commit_and_tree(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path)
    identity = git_release_identity(repo, "release-v2")
    code_manifest = build_code_manifest(repo, "release-v2", config, identity=identity)
    bundle = tmp_path / "source.bundle"
    create_source_bundle(repo, "release-v2", bundle)
    verify_source_bundle(
        bundle,
        "release-v2",
        identity,
        code_manifest=code_manifest,
        config=config,
    )

    wrong = dict(identity)
    wrong["tree"] = "0" * 40
    with pytest.raises(ReleaseError, match="tree mismatch"):
        verify_source_bundle(bundle, "release-v2", wrong)


def test_release_inventory_rejects_extra_missing_and_tampered_files(tmp_path: Path) -> None:
    release = tmp_path / "release"
    (release / "nested").mkdir(parents=True)
    (release / "artifact.bin").write_bytes(b"artifact")
    (release / "nested/evidence.json").write_text("{}\n", encoding="utf-8")
    manifest = {
        "schema": "waybill-formal-release-manifest/v2",
        "identity": {},
        "bindings": {},
        "assets": _release_assets(release),
    }
    write_canonical_json(release / "release-manifest.json", manifest)
    write_sha256sums(release)
    assert verify_release_inventory(release) == manifest

    (release / "extra.txt").write_text("not inventoried\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="inventory mismatch"):
        verify_release_inventory(release)
    (release / "extra.txt").unlink()
    (release / "artifact.bin").write_bytes(b"tampered")
    with pytest.raises(ReleaseError, match="checksum mismatch"):
        verify_release_inventory(release)


def test_container_metadata_and_spdx_sbom_require_release_bindings(tmp_path: Path) -> None:
    image = tmp_path / "formal-image.tar"
    bindings = {
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "code_manifest_sha256": "c" * 64,
        "protocol_sha256": "d" * 64,
    }
    derived = _write_image_tar(image, "formal-runner", bindings)
    metadata = {
        "schema": "waybill-container-image-metadata/v2",
        "role": "formal-runner",
        "platform": "linux/amd64",
        **derived,
        "image_tar_sha256": sha256_file(image),
        "bindings": bindings,
    }
    assert verify_image_metadata(
        image,
        metadata,
        role="formal-runner",
        bindings=bindings,
        user="10003:10003",
    ) == metadata
    sbom_path = tmp_path / "formal.spdx.json"
    _write_sbom(
        sbom_path,
        role="formal-runner",
        metadata=metadata,
        bindings=bindings,
    )
    assert verify_sbom(
        sbom_path,
        role="formal-runner",
        image_metadata=metadata,
        bindings=bindings,
    )["packages"]

    relationship_sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    described = relationship_sbom.pop("documentDescribes")
    relationship_sbom["relationships"] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relatedSpdxElement": described[0],
            "relationshipType": "DESCRIBES",
        }
    ]
    _write_json(sbom_path, relationship_sbom)
    assert verify_sbom(
        sbom_path,
        role="formal-runner",
        image_metadata=metadata,
        bindings=bindings,
    )["relationships"]

    stale = dict(metadata)
    stale["bindings"] = {**bindings, "git_commit": "f" * 40}
    with pytest.raises(ReleaseError, match="source bindings mismatch"):
        verify_image_metadata(
            image,
            stale,
            role="formal-runner",
            bindings=bindings,
            user="10003:10003",
        )
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    sbom["waybillBinding"]["git_tree"] = "0" * 40
    _write_json(sbom_path, sbom)
    with pytest.raises(ReleaseError, match="SBOM binding mismatch"):
        verify_sbom(
            sbom_path,
            role="formal-runner",
            image_metadata=metadata,
            bindings=bindings,
        )


def test_formal_runner_layers_must_embed_exact_tagged_source(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path / "fixture")
    identity = git_release_identity(repo, "release-v2")
    code_manifest = build_code_manifest(repo, "release-v2", config, identity=identity)
    protocol = MODULE.protocol_binding(repo, "release-v2", config)
    bindings = {
        "git_commit": identity["commit"],
        "git_tree": identity["tree"],
        "code_manifest_sha256": canonical_sha256(code_manifest),
        "protocol_sha256": protocol["canonical_sha256"],
    }
    image = tmp_path / "formal-image.tar"
    _write_image_tar(image, "formal-runner", bindings)
    receipt = verify_formal_runner_embedded_source(
        image,
        code_manifest=code_manifest,
        config=config,
        bindings=bindings,
    )
    assert receipt["file_count"] == 1

    tampered = tmp_path / "tampered-formal-image.tar"
    _write_image_tar(
        tampered,
        "formal-runner",
        bindings,
        formal_source=b"VALUE = 'tampered'\n",
    )
    with pytest.raises(ReleaseError, match="embedded source blob mismatch"):
        verify_formal_runner_embedded_source(
            tampered,
            code_manifest=code_manifest,
            config=config,
            bindings=bindings,
        )


def test_image_metadata_accepts_modern_docker_save_oci_layout(tmp_path: Path) -> None:
    _, config = _make_tagged_repo(tmp_path / "fixture")
    bindings = {
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "code_manifest_sha256": "c" * 64,
        "protocol_sha256": "d" * 64,
    }
    preflight = {
        "schema": "waybill-release-preflight/v2",
        "identity": {
            "commit": bindings["git_commit"],
            "tree": bindings["git_tree"],
        },
        "code_manifest_sha256": bindings["code_manifest_sha256"],
        "protocol": {"canonical_sha256": bindings["protocol_sha256"]},
    }
    image = tmp_path / "modern-docker-save.tar"
    derived = _write_oci_docker_save_tar(image, "formal-runner", bindings)
    metadata = create_image_metadata(
        image_tar=image,
        role="formal-runner",
        image_ref=derived["image_ref"],
        config=config,
        preflight=preflight,
    )
    assert metadata["archive_format"] == "oci-layout"
    assert metadata["image_digest"] == derived["image_digest"]
    assert metadata["config_digest"] == derived["config_digest"]


def test_release_tool_derives_metadata_and_binds_scanner_outputs(
    tmp_path: Path,
) -> None:
    bindings = {
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "code_manifest_sha256": "c" * 64,
        "protocol_sha256": "d" * 64,
    }
    preflight = {
        "schema": "waybill-release-preflight/v2",
        "identity": {
            "commit": bindings["git_commit"],
            "tree": bindings["git_tree"],
        },
        "code_manifest_sha256": bindings["code_manifest_sha256"],
        "protocol": {"canonical_sha256": bindings["protocol_sha256"]},
    }
    config = {
        "containers": {
            "scanner": {
                "name": "trivy",
                "report_schema_version": 2,
                "version": "0.72.0",
            },
            "roles": {
                "formal-runner": {
                    "embedded_source_paths": ["src"],
                    "platform": "linux/amd64",
                    "user": "10003:10003",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
                "charger": {
                    "platform": "linux/amd64",
                    "user": "10002:10002",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
                "postgres": {
                    "platform": "linux/amd64",
                    "user": "70:70",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
                "receiver-signer": {
                    "platform": "linux/amd64",
                    "user": "10001:10001",
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": [],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 0,
                    },
                },
            }
        }
    }
    image = tmp_path / "formal-image.tar"
    derived = _write_image_tar(image, "formal-runner", bindings)
    metadata = create_image_metadata(
        image_tar=image,
        role="formal-runner",
        image_ref=derived["image_ref"],
        config=config,
        preflight=preflight,
    )
    assert metadata["bindings"] == bindings
    assert metadata["user"] == "10003:10003"

    metadata_path = tmp_path / "formal-metadata.json"
    raw_sbom_path = tmp_path / "formal-raw.spdx.json"
    _write_json(metadata_path, metadata)
    _write_sbom(
        raw_sbom_path,
        role="formal-runner",
        metadata=metadata,
        bindings=bindings,
    )
    raw_sbom = json.loads(raw_sbom_path.read_text(encoding="utf-8"))
    raw_sbom.pop("waybillBinding")
    _write_json(raw_sbom_path, raw_sbom)
    bound = bind_scanner_sbom(
        raw_sbom_path=raw_sbom_path,
        metadata_path=metadata_path,
        role="formal-runner",
        preflight=preflight,
    )
    assert bound["waybillBinding"]["image_digest"] == metadata["image_digest"]
    assert bound["waybillBinding"]["git_commit"] == bindings["git_commit"]

    raw_vulnerability_path = tmp_path / "formal-raw.trivy.json"
    _write_vulnerability_report(
        raw_vulnerability_path,
        role="formal-runner",
        metadata=metadata,
        bindings=bindings,
    )
    raw_report = json.loads(raw_vulnerability_path.read_text(encoding="utf-8"))
    raw_report.pop("waybillBinding")
    _write_json(raw_vulnerability_path, raw_report)
    bound_report = bind_scanner_vulnerability_report(
        raw_report_path=raw_vulnerability_path,
        metadata_path=metadata_path,
        role="formal-runner",
        preflight=preflight,
        config=config,
    )
    assert bound_report["waybillBinding"]["scan_image_id"] == metadata["image_digest"]
    assert bound_report["waybillBinding"]["summary"]["total_high_critical"] == 0


def test_trivy_report_enforces_image_identity_and_vulnerability_policy(
    tmp_path: Path,
) -> None:
    bindings = {
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "code_manifest_sha256": "c" * 64,
        "protocol_sha256": "d" * 64,
    }
    image = tmp_path / "formal-image.tar"
    derived = _write_image_tar(image, "formal-runner", bindings)
    metadata = {
        "schema": "waybill-container-image-metadata/v2",
        "role": "formal-runner",
        "platform": "linux/amd64",
        **derived,
        "image_tar_sha256": sha256_file(image),
        "bindings": bindings,
    }
    config = {
        "containers": {
            "scanner": {
                "name": "trivy",
                "report_schema_version": 2,
                "version": "0.72.0",
            },
            "roles": {
                "formal-runner": {
                    "vulnerability_policy": {
                        "allowed_unfixed_high_critical_ids": ["CVE-2099-0001"],
                        "max_fixable": 0,
                        "max_fixable_high_critical": 0,
                        "max_high_critical": 1,
                    }
                }
            },
        }
    }
    report_path = tmp_path / "formal.trivy.json"
    _write_vulnerability_report(
        report_path,
        role="formal-runner",
        metadata=metadata,
        bindings=bindings,
        vulnerabilities=[
            {
                "VulnerabilityID": "CVE-2099-0001",
                "Severity": "HIGH",
                "FixedVersion": "",
            }
        ],
    )
    verified = verify_vulnerability_report(
        report_path,
        role="formal-runner",
        image_metadata=metadata,
        bindings=bindings,
        config=config,
    )
    assert verified["waybillBinding"]["summary"]["total_high_critical"] == 1

    wrong_image = json.loads(report_path.read_text(encoding="utf-8"))
    wrong_image["Metadata"]["ImageID"] = "sha256:" + "0" * 64
    _write_json(report_path, wrong_image)
    with pytest.raises(ReleaseError, match="image ID mismatch"):
        verify_vulnerability_report(
            report_path,
            role="formal-runner",
            image_metadata=metadata,
            bindings=bindings,
            config=config,
        )

    _write_vulnerability_report(
        report_path,
        role="formal-runner",
        metadata=metadata,
        bindings=bindings,
        vulnerabilities=[
            {
                "VulnerabilityID": "CVE-2099-0002",
                "Severity": "CRITICAL",
                "FixedVersion": "1.2.3",
            }
        ],
    )
    with pytest.raises(ReleaseError, match="fixable vulnerability threshold"):
        verify_vulnerability_report(
            report_path,
            role="formal-runner",
            image_metadata=metadata,
            bindings=bindings,
            config=config,
        )


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is not installed")
def test_minimal_release_build_is_self_verifying(tmp_path: Path) -> None:
    repo, config = _make_tagged_repo(tmp_path / "fixture")
    identity = git_release_identity(repo, "release-v2")
    code = build_code_manifest(repo, "release-v2", config, identity=identity)
    protocol = MODULE.protocol_binding(repo, "release-v2", config)
    bindings = {
        "git_commit": identity["commit"],
        "git_tree": identity["tree"],
        "code_manifest_sha256": canonical_sha256(code),
        "protocol_sha256": protocol["canonical_sha256"],
    }
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    image_args: list[str] = []
    metadata_args: list[str] = []
    sbom_args: list[str] = []
    vulnerability_args: list[str] = []
    for role, prefix in (
        ("formal-runner", "formal"),
        ("charger", "charger"),
        ("postgres", "postgres"),
        ("receiver-signer", "receiver-signer"),
    ):
        image = inputs / f"{prefix}-image.tar"
        derived = _write_image_tar(image, role, bindings)
        metadata = {
            "schema": "waybill-container-image-metadata/v2",
            "role": role,
            "platform": "linux/amd64",
            **derived,
            "image_tar_sha256": sha256_file(image),
            "bindings": bindings,
        }
        metadata_path = inputs / f"{prefix}-metadata.json"
        sbom_path = inputs / f"{prefix}-sbom.spdx.json"
        vulnerability_path = inputs / f"{prefix}-vulnerabilities.trivy.json"
        _write_json(metadata_path, metadata)
        _write_sbom(
            sbom_path,
            role=role,
            metadata=metadata,
            bindings=bindings,
        )
        _write_vulnerability_report(
            vulnerability_path,
            role=role,
            metadata=metadata,
            bindings=bindings,
        )
        image_args.append(f"{role}={image}")
        metadata_args.append(f"{role}={metadata_path}")
        sbom_args.append(f"{role}={sbom_path}")
        vulnerability_args.append(f"{role}={vulnerability_path}")
    output = tmp_path / "release"
    args = SimpleNamespace(
        repo=repo,
        tag="release-v2",
        output=output,
        image=image_args,
        image_metadata=metadata_args,
        sbom=sbom_args,
        vulnerability_report=vulnerability_args,
    )
    build_release(args, config)
    verify_release(output, config=config)
    assert (output / "prover.tar.zst").is_file()
    assert (output / "source.bundle").is_file()
    assert verify_release_inventory(output)["bindings"] == bindings


def test_canonical_hash_is_stable_for_manifest_key_order() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})
