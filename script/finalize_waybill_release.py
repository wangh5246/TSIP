#!/usr/bin/env python3
"""Fail-closed builder and verifier for a Waybill formal release.

The annotated Git tag is the source of truth for source artifacts.  Large
prover artifacts and pre-built container images are supplied separately and
bound to the tagged source by explicit manifests.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ROLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1\n"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 16 * 1024 * 1024 * 1024
MAX_ZSTD_OUTPUT_BYTES = 16 * 1024 * 1024 * 1024
CONTAINER_BINDING_LABELS = {
    "org.opencontainers.image.revision": "git_commit",
    "io.waybill.git.tree": "git_tree",
    "io.waybill.code-manifest.sha256": "code_manifest_sha256",
    "io.waybill.protocol.sha256": "protocol_sha256",
}


class ReleaseError(RuntimeError):
    """A release invariant was not satisfied."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(
    handle: Any,
    *,
    max_bytes: int = MAX_ARCHIVE_MEMBER_BYTES,
    label: str = "stream",
) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
        if size > max_bytes:
            raise ReleaseError(f"{label} exceeds the configured size limit")
    return digest.hexdigest(), size


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def write_new_canonical_json(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise ReleaseError(f"refusing to overwrite existing output: {path}")
    write_canonical_json(path, value)


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    input_data: bytes | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise ReleaseError(f"cannot execute {command[0]}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseError(f"command failed ({' '.join(command)}): {detail}")
    return completed.stdout


def run_git(repo: Path, *args: str) -> bytes:
    return _run(("git", "-C", str(repo), *args))


def _safe_relative(raw: str, *, label: str = "path") -> str:
    if not raw or "\\" in raw or any(ord(char) < 32 for char in raw):
        raise ReleaseError(f"unsafe {label}: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseError(f"unsafe {label}: {raw!r}")
    normalized = path.as_posix()
    if normalized != raw:
        raise ReleaseError(f"non-canonical {label}: {raw!r}")
    return normalized


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _load_json_value(data: bytes, *, label: str, max_bytes: int = MAX_JSON_BYTES) -> Any:
    if len(data) > max_bytes:
        raise ReleaseError(f"JSON input exceeds the configured size limit: {label}")
    try:
        return json.loads(
            data,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseError(f"invalid JSON in {label}: {exc}") from exc


def _load_json_bytes(data: bytes, *, label: str) -> dict[str, Any]:
    value = _load_json_value(data, label=label)
    if not isinstance(value, dict):
        raise ReleaseError(f"{label} must contain a JSON object")
    return value


def load_config(path: Path) -> dict[str, Any]:
    config = _load_json_bytes(path.read_bytes(), label=str(path))
    if config.get("schema") != "waybill-release-finalizer-config/v2":
        raise ReleaseError("unsupported release config schema")
    return config


def verify_release_blockers(config: Mapping[str, Any]) -> None:
    blockers = config.get("release_blockers", [])
    if not isinstance(blockers, list) or any(
        not isinstance(blocker, str) or not blocker.strip() for blocker in blockers
    ):
        raise ReleaseError("config.release_blockers must be an array of non-empty strings")
    if blockers:
        raise ReleaseError("release is blocked: " + "; ".join(blockers))


def _git_ref(tag: str) -> str:
    if not tag or tag.startswith("-") or any(char.isspace() for char in tag):
        raise ReleaseError(f"invalid tag name: {tag!r}")
    return f"refs/tags/{tag}"


def git_release_identity(
    repo: Path,
    tag: str,
    *,
    require_head: bool = True,
    require_clean: bool = True,
) -> dict[str, Any]:
    """Resolve and validate an annotated tag, its commit, and its tree."""

    repo = repo.resolve()
    ref = _git_ref(tag)
    run_git(repo, "check-ref-format", ref)
    tag_object = run_git(repo, "rev-parse", "--verify", ref).decode().strip()
    object_type = run_git(repo, "cat-file", "-t", ref).decode().strip()
    if object_type != "tag":
        raise ReleaseError(f"{tag} is not an annotated tag")
    commit = run_git(repo, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    tree = run_git(repo, "rev-parse", f"{ref}^{{tree}}").decode().strip()
    commit_time = int(run_git(repo, "show", "-s", "--format=%ct", commit).decode().strip())
    if require_head:
        head = run_git(repo, "rev-parse", "HEAD").decode().strip()
        if head != commit:
            raise ReleaseError(f"tag commit {commit} is not HEAD {head}")
    if require_clean:
        status = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        if status:
            preview = status.decode("utf-8", errors="replace").splitlines()[:5]
            raise ReleaseError("working tree is not clean: " + "; ".join(preview))
    return {
        "tag": tag,
        "tag_object": tag_object,
        "commit": commit,
        "tree": tree,
        "commit_time_epoch": commit_time,
    }


def git_blob(repo: Path, tag: str, path: str) -> bytes:
    path = _safe_relative(path, label="Git path")
    return run_git(repo, "show", f"{_git_ref(tag)}:{path}")


def is_lfs_pointer(data: bytes) -> bool:
    return data.startswith(LFS_HEADER) and b"oid sha256:" in data[:1024]


def _tree_entries(repo: Path, tag: str, paths: Iterable[str]) -> dict[str, dict[str, str]]:
    safe_paths = sorted({_safe_relative(path, label="configured Git path") for path in paths})
    if not safe_paths:
        return {}
    literal_paths = [f":(literal){path}" for path in safe_paths]
    raw = run_git(repo, "ls-tree", "-r", "-z", _git_ref(tag), "--", *literal_paths)
    entries: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\x00"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseError("cannot parse git ls-tree output") from exc
        entries[path] = {"mode": mode, "type": object_type, "object": object_id}
    return entries


def expand_required_tag_paths(
    repo: Path,
    tag: str,
    config: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    section = config.get("code_manifest")
    if not isinstance(section, dict):
        raise ReleaseError("config.code_manifest must be an object")
    required = section.get("required_paths", [])
    scopes = section.get("scopes", [])
    if not isinstance(required, list) or not isinstance(scopes, list):
        raise ReleaseError("code manifest paths and scopes must be arrays")
    entries = _tree_entries(repo, tag, [*required, *scopes])
    for path in required:
        safe = _safe_relative(str(path), label="required path")
        if safe not in entries:
            raise ReleaseError(f"required tagged path is missing: {safe}")
    if not entries:
        raise ReleaseError("code manifest selected no tagged files")
    for path, entry in entries.items():
        if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise ReleaseError(f"tagged path is not a regular file: {path}")
        data = git_blob(repo, tag, path)
        if is_lfs_pointer(data):
            raise ReleaseError(f"Git LFS pointer is forbidden in active release scope: {path}")
    return entries


def build_code_manifest(
    repo: Path,
    tag: str,
    config: Mapping[str, Any],
    *,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identity = dict(identity or git_release_identity(repo, tag))
    entries = expand_required_tag_paths(repo, tag, config)
    files: list[dict[str, Any]] = []
    for path in sorted(entries):
        data = git_blob(repo, tag, path)
        files.append(
            {
                "path": path,
                "mode": entries[path]["mode"],
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    return {
        "schema": "waybill-code-manifest/v2",
        "tag": identity["tag"],
        "tag_object": identity["tag_object"],
        "git_commit": identity["commit"],
        "git_tree": identity["tree"],
        "commit_time_epoch": identity["commit_time_epoch"],
        "file_count": len(files),
        "files": files,
    }


def _resolve_tag_relative(base_path: str, relative: str) -> str:
    if not relative or "\\" in relative:
        raise ReleaseError(f"unsafe relative binding: {relative!r}")
    candidate = PurePosixPath(base_path).parent.joinpath(relative)
    parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ReleaseError(f"binding escapes repository: {relative!r}")
            parts.pop()
        else:
            parts.append(part)
    return _safe_relative("/".join(parts), label="resolved binding")


def _profile_semantic_sha256(profile: Mapping[str, Any]) -> str:
    payload = dict(profile)
    for key in (
        "profile_sha256",
        "policy_profile_commitment",
        "verification_key_path",
        "tariff_artifact_path",
    ):
        payload.pop(key, None)
    return canonical_sha256(payload)


def _expect_hash(value: Any, *, label: str) -> str:
    text = str(value)
    if not SHA256_RE.fullmatch(text):
        raise ReleaseError(f"{label} is not a lowercase SHA-256 digest")
    return text


def _verify_hash_mapping(
    repo: Path,
    tag: str,
    declared: Any,
    configured: Any,
    *,
    label: str,
) -> None:
    if not isinstance(declared, dict) or not isinstance(configured, dict):
        raise ReleaseError(f"{label} hash maps must be objects")
    if set(declared) != set(configured):
        raise ReleaseError(f"{label} hash keys do not match configured keys")
    for key, path in configured.items():
        expected = _expect_hash(declared[key], label=f"{label}.{key}")
        actual = sha256_bytes(git_blob(repo, tag, str(path)))
        if actual != expected:
            raise ReleaseError(f"{label} hash mismatch for {key}: {actual} != {expected}")


def _verify_receipt_requirements(
    endpoint: Mapping[str, Any],
    circuit: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    requirements = config.get("receipt_requirements")
    if not isinstance(requirements, dict):
        raise ReleaseError("config.receipt_requirements must be an object")
    if endpoint.get("schema") != requirements.get("endpoint_schema"):
        raise ReleaseError("endpoint receipt schema mismatch")
    if circuit.get("schema") != requirements.get("circuit_schema"):
        raise ReleaseError("circuit receipt schema mismatch")
    for section_name, receipt in (("endpoint", endpoint), ("circuit", circuit)):
        assertions = requirements.get(section_name)
        if not isinstance(assertions, dict) or not assertions:
            raise ReleaseError(f"receipt requirements for {section_name} must be a non-empty object")
        for key, expected in assertions.items():
            if receipt.get(key) != expected:
                raise ReleaseError(
                    f"{section_name} receipt does not assert {key}={expected!r}"
                )
    gates = requirements.get("endpoint_gates")
    declared_gates = endpoint.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ReleaseError("receipt_requirements.endpoint_gates must be a non-empty array")
    if not isinstance(declared_gates, dict):
        raise ReleaseError("endpoint receipt gates must be an object")
    expected_gate_names = {str(name) for name in gates}
    if set(declared_gates) != expected_gate_names:
        raise ReleaseError("endpoint receipt gate keys do not match the configured gate closure")
    for name in sorted(expected_gate_names):
        if declared_gates.get(name) is not True:
            raise ReleaseError(f"endpoint receipt gate is not true: {name}")


def _recompute_policy_profile(
    profile: Mapping[str, Any],
    tariff_blob: bytes,
    *,
    tariff_path: str,
) -> Any:
    """Recompute the production profile commitment and tariff Merkle root."""

    try:
        from common.policy_profile import (  # pylint: disable=import-outside-toplevel
            POLICY_PROFILE_COMMITMENT_VERSION,
            POLICY_PROFILE_DOMAIN,
            PolicyProfile,
        )
        from common.settlement import TariffTable  # pylint: disable=import-outside-toplevel

        if profile.get("domain_sep") != POLICY_PROFILE_DOMAIN:
            raise ValueError("policy profile domain separator mismatch")
        if profile.get("commitment_version") != POLICY_PROFILE_COMMITMENT_VERSION:
            raise ValueError("policy profile commitment version mismatch")
        canonical_profile = PolicyProfile.from_dict(dict(profile))
        tariff = _load_json_bytes(tariff_blob, label=tariff_path)
        table = TariffTable(
            tariff_version=int(tariff["tariff_version"]),
            grid_w=int(tariff["grid_w"]),
            cell_zones={int(key): int(value) for key, value in tariff["cell_zones"].items()},
            zone_rates_cents_per_m={
                int(key): int(value)
                for key, value in tariff["zone_rates_cents_per_m"].items()
            },
        )
        computed_root = int(table.root(int(canonical_profile.tariff_tree_depth)))
        if int(tariff.get("tree_depth", -1)) != int(canonical_profile.tariff_tree_depth):
            raise ValueError("tariff artifact tree depth mismatch")
        if int(tariff.get("tariff_root", -1)) != computed_root:
            raise ValueError("tariff artifact declared root mismatch")
        if int(tariff.get("max_zone_rate_cents_per_m", -1)) != int(
            table.max_zone_rate_cents_per_m
        ):
            raise ValueError("tariff artifact declared maximum rate mismatch")
        canonical_profile.assert_tariff_matches(table)
        return canonical_profile
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseError(f"canonical policy profile/tariff validation failed: {exc}") from exc


def _verify_public_signal_binding(
    public_blob: bytes,
    *,
    public_path: str,
    circuit: Mapping[str, Any],
    endpoint: Mapping[str, Any],
    profile: Any,
) -> list[str]:
    try:
        from common.settlement import SNARK_FIELD  # pylint: disable=import-outside-toplevel
        from common.settlement_v6 import (  # pylint: disable=import-outside-toplevel
            PUBLIC_SIGNAL_ORDER_V6,
        )
    except ImportError as exc:
        raise ReleaseError(f"cannot import the production public-signal definition: {exc}") from exc

    value = _load_json_value(public_blob, label=public_path)
    if not isinstance(value, list) or len(value) != len(PUBLIC_SIGNAL_ORDER_V6):
        raise ReleaseError("public signal vector has the wrong length")
    signals: list[str] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, str) or re.fullmatch(r"0|[1-9][0-9]*", raw) is None:
            raise ReleaseError(f"public signal {index} is not a canonical decimal field element")
        integer = int(raw)
        if integer < 0 or integer >= SNARK_FIELD:
            raise ReleaseError(f"public signal {index} is outside the SNARK field")
        signals.append(raw)
    expected_order = list(PUBLIC_SIGNAL_ORDER_V6)
    if circuit.get("public_signal_order") != expected_order:
        raise ReleaseError("circuit receipt public-signal order mismatch")
    if circuit.get("public_signals") != signals:
        raise ReleaseError("circuit receipt public signals do not match public.json")
    if circuit.get("python_reference_public_signals") != signals:
        raise ReleaseError("Python reference public signals do not match public.json")

    by_name = dict(zip(expected_order, signals))
    expected_profile_fields = {
        "tariff_root": int(profile.tariff_root),
        "policy_profile_commitment": int(profile.commitment),
        "tariff_version": int(profile.tariff_version),
        "cadence_sec": int(profile.cadence_sec),
        "tier_vmax_mps": int(profile.tier_vmax_mps),
        "tier_vmax_sq": int(profile.tier_vmax_sq),
        "mode_vmax_sq": int(profile.mode_vmax_sq),
        "cap_policy_sq": int(profile.cap_policy_sq),
        "max_zone_rate_cents_per_m": int(profile.max_zone_rate_cents_per_m),
        "max_dt_sec": int(profile.max_dt_sec),
    }
    for name, expected in expected_profile_fields.items():
        if int(by_name[name]) != expected:
            raise ReleaseError(f"public signal is not bound to the canonical profile: {name}")
    accepted = endpoint.get("accepted")
    if not isinstance(accepted, dict) or str(accepted.get("policy_profile_commitment")) != str(
        profile.commitment
    ):
        raise ReleaseError("endpoint receipt accepted result is not bound to the profile")
    return signals


def _run_groth16_verify(vkey_blob: bytes, public_blob: bytes, proof_blob: bytes) -> None:
    """Run the production Groth16 verifier; tests may replace this with a strict stub."""

    with tempfile.TemporaryDirectory(prefix="waybill-release-proof-") as raw_temp:
        temporary = Path(raw_temp)
        vkey = temporary / "verification_key.json"
        public = temporary / "public.json"
        proof = temporary / "proof.json"
        vkey.write_bytes(vkey_blob)
        public.write_bytes(public_blob)
        proof.write_bytes(proof_blob)
        try:
            completed = subprocess.run(
                ("snarkjs", "groth16", "verify", str(vkey), str(public), str(proof)),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReleaseError(f"cannot execute Groth16 verification: {exc}") from exc
        stdout = completed.stdout.decode("utf-8", errors="replace")
        if completed.returncode != 0 or "OK!" not in stdout:
            detail = (stdout + completed.stderr.decode("utf-8", errors="replace")).strip()
            raise ReleaseError(f"Groth16 proof verification failed: {detail}")


def verify_profile_and_receipts(
    repo: Path,
    tag: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify policy/vkey and receipt hash bindings from tagged blobs only."""

    bindings = config.get("bindings")
    if not isinstance(bindings, dict):
        raise ReleaseError("config.bindings must be an object")
    profile_path = _safe_relative(str(bindings.get("profile", "")), label="profile path")
    endpoint_path = _safe_relative(
        str(bindings.get("endpoint_receipt", "")), label="endpoint receipt path"
    )
    circuit_path = _safe_relative(
        str(bindings.get("circuit_receipt", "")), label="circuit receipt path"
    )
    profile_blob = git_blob(repo, tag, profile_path)
    profile = _load_json_bytes(profile_blob, label=profile_path)
    endpoint = _load_json_bytes(git_blob(repo, tag, endpoint_path), label=endpoint_path)
    circuit = _load_json_bytes(git_blob(repo, tag, circuit_path), label=circuit_path)
    _verify_receipt_requirements(endpoint, circuit, config)
    _expect_hash(
        circuit.get("receiver_attestation_sha256"),
        label="circuit.receiver_attestation_sha256",
    )
    _expect_hash(
        circuit.get("previous_attestation_sha256"),
        label="circuit.previous_attestation_sha256",
    )

    semantic_hash = _profile_semantic_sha256(profile)
    if _expect_hash(profile.get("profile_sha256"), label="profile.profile_sha256") != semantic_hash:
        raise ReleaseError("profile semantic SHA-256 does not match profile_sha256")
    vkey_path = _resolve_tag_relative(profile_path, str(profile.get("verification_key_path", "")))
    tariff_path = _resolve_tag_relative(profile_path, str(profile.get("tariff_artifact_path", "")))
    vkey_hash = sha256_bytes(git_blob(repo, tag, vkey_path))
    declared_vkey = _expect_hash(
        profile.get("verification_key_hash"), label="profile.verification_key_hash"
    )
    if vkey_hash != declared_vkey:
        raise ReleaseError("profile verification-key hash does not match tagged blob")
    tariff_blob = git_blob(repo, tag, tariff_path)
    canonical_profile = _recompute_policy_profile(
        profile,
        tariff_blob,
        tariff_path=tariff_path,
    )
    if semantic_hash != canonical_profile.profile_sha256:
        raise ReleaseError("profile semantic SHA-256 differs from the production recomputation")

    _verify_hash_mapping(
        repo,
        tag,
        endpoint.get("code_sha256"),
        bindings.get("endpoint_code"),
        label="endpoint code",
    )
    _verify_hash_mapping(
        repo,
        tag,
        circuit.get("code_sha256"),
        bindings.get("circuit_code"),
        label="circuit code",
    )
    _verify_hash_mapping(
        repo,
        tag,
        endpoint.get("artifact_sha256"),
        bindings.get("endpoint_artifacts"),
        label="endpoint artifact",
    )
    policy_map = bindings.get("endpoint_policy_artifacts")
    if policy_map is None:
        policy_map = {PurePosixPath(profile_path).name: profile_path, PurePosixPath(tariff_path).name: tariff_path}
    _verify_hash_mapping(
        repo,
        tag,
        endpoint.get("policy_artifact_sha256"),
        policy_map,
        label="endpoint policy artifact",
    )
    circuit_artifacts = bindings.get("circuit_artifacts")
    if not isinstance(circuit_artifacts, dict):
        raise ReleaseError("bindings.circuit_artifacts must be an object")
    declared_circuit = circuit.get("artifact_sha256")
    if not isinstance(declared_circuit, dict):
        raise ReleaseError("circuit receipt artifact_sha256 must be an object")
    prover = config.get("prover")
    prover_files = prover.get("files") if isinstance(prover, dict) else None
    if not isinstance(prover_files, dict) or not prover_files:
        raise ReleaseError("config.prover.files must be a non-empty object")
    expected_circuit_hashes = set(circuit_artifacts) | set(prover_files)
    if set(declared_circuit) != expected_circuit_hashes:
        raise ReleaseError(
            "circuit receipt artifact hashes do not cover the exact tagged/prover role closure"
        )
    for key, path in circuit_artifacts.items():
        if key not in declared_circuit:
            raise ReleaseError(f"circuit receipt is missing artifact hash: {key}")
        expected = _expect_hash(declared_circuit[key], label=f"circuit artifact.{key}")
        actual = sha256_bytes(git_blob(repo, tag, str(path)))
        if actual != expected:
            raise ReleaseError(f"circuit artifact hash mismatch for {key}")
    for role in prover_files:
        _expect_hash(declared_circuit.get(role), label=f"circuit artifact.{role}")

    if str(circuit.get("policy_profile_sha256")) != semantic_hash:
        raise ReleaseError("circuit receipt is not bound to the profile semantic hash")
    if str(circuit.get("policy_profile_commitment")) != str(
        canonical_profile.commitment
    ):
        raise ReleaseError("circuit receipt profile commitment mismatch")
    public_key = "public_json"
    proof_key = "proof_json"
    if public_key not in circuit_artifacts or proof_key not in circuit_artifacts:
        raise ReleaseError("circuit_artifacts must bind proof_json and public_json")
    public_blob = git_blob(repo, tag, str(circuit_artifacts[public_key]))
    proof_blob = git_blob(repo, tag, str(circuit_artifacts[proof_key]))
    _verify_public_signal_binding(
        public_blob,
        public_path=str(circuit_artifacts[public_key]),
        circuit=circuit,
        endpoint=endpoint,
        profile=canonical_profile,
    )
    _run_groth16_verify(git_blob(repo, tag, vkey_path), public_blob, proof_blob)
    return {
        "profile_path": profile_path,
        "profile_file_sha256": sha256_bytes(profile_blob),
        "profile_semantic_sha256": semantic_hash,
        "policy_profile_commitment": str(canonical_profile.commitment),
        "tariff_path": tariff_path,
        "tariff_sha256": sha256_bytes(tariff_blob),
        "verification_key_path": vkey_path,
        "verification_key_sha256": vkey_hash,
        "endpoint_receipt_path": endpoint_path,
        "endpoint_receipt_sha256": sha256_bytes(git_blob(repo, tag, endpoint_path)),
        "circuit_receipt_path": circuit_path,
        "circuit_receipt_sha256": sha256_bytes(git_blob(repo, tag, circuit_path)),
        "circuit_artifact_sha256": dict(declared_circuit),
    }


def protocol_binding(repo: Path, tag: str, config: Mapping[str, Any]) -> dict[str, str]:
    path = _safe_relative(str(config.get("protocol_path", "")), label="protocol path")
    blob = git_blob(repo, tag, path)
    protocol = _load_json_bytes(blob, label=path)
    return {
        "path": path,
        "file_sha256": sha256_bytes(blob),
        "canonical_sha256": canonical_sha256(protocol),
    }


def verify_tagged_config(
    repo: Path,
    tag: str,
    config: Mapping[str, Any],
) -> str:
    """Require the controlling finalizer config itself to be a tagged blob."""

    path = _safe_relative(str(config.get("config_path", "")), label="release config path")
    tagged = _load_json_bytes(git_blob(repo, tag, path), label=path)
    if canonical_sha256(tagged) != canonical_sha256(config):
        raise ReleaseError("working release config does not match the tagged config blob")
    return path


def build_prover_manifest(
    prover_dir: Path,
    prover_config: Mapping[str, Any],
    *,
    bindings: Mapping[str, Any],
    receipt_artifact_sha256: Mapping[str, Any] | None = None,
    ptau_root: Path | None = None,
) -> dict[str, Any]:
    prover_dir = prover_dir.resolve()
    files_config = prover_config.get("files")
    if not isinstance(files_config, dict) or not files_config:
        raise ReleaseError("prover.files must be a non-empty object")
    files: list[dict[str, Any]] = []
    selected = {
        _safe_relative(str(raw_path), label=f"prover file {role}")
        for role, raw_path in files_config.items()
    }
    raw_allowed_extra = prover_config.get("allowed_extra", [])
    if not isinstance(raw_allowed_extra, list):
        raise ReleaseError("prover.allowed_extra must be an array")
    allowed_extra = {
        _safe_relative(str(path), label="allowed prover extra")
        for path in raw_allowed_extra
    }
    actual = {
        path.relative_to(prover_dir).as_posix()
        for path in prover_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    unsafe = [path for path in prover_dir.rglob("*") if path.is_symlink()]
    if unsafe:
        raise ReleaseError(f"prover directory contains symlink: {unsafe[0]}")
    extras = actual - selected - allowed_extra
    if extras:
        raise ReleaseError("unexpected prover files: " + ", ".join(sorted(extras)))
    if not isinstance(receipt_artifact_sha256, Mapping):
        raise ReleaseError("a circuit receipt hash map is required for every prover file")
    receipt_hashes = receipt_artifact_sha256
    missing_roles = set(files_config) - set(receipt_hashes)
    if missing_roles:
        raise ReleaseError(
            "circuit receipt is missing prover artifact hashes: "
            + ", ".join(sorted(missing_roles))
        )
    for role, raw_path in sorted(files_config.items()):
        path = _safe_relative(str(raw_path), label=f"prover file {role}")
        source = prover_dir / path
        if not source.is_file() or source.is_symlink():
            raise ReleaseError(f"required prover file is missing or unsafe: {source}")
        digest = sha256_file(source)
        expected = _expect_hash(receipt_hashes[role], label=f"receipt artifact.{role}")
        if digest != expected:
            raise ReleaseError(f"prover artifact does not match receipt: {role}")
        files.append(
            {
                "path": path,
                "role": role,
                "size": source.stat().st_size,
                "sha256": digest,
                "mode": "0755" if source.stat().st_mode & 0o111 else "0644",
            }
        )
    ptau_record: dict[str, Any] | None = None
    ptau = prover_config.get("test_ptau")
    if ptau is not None:
        if not isinstance(ptau, dict) or ptau_root is None:
            raise ReleaseError("test PTAU binding requires ptau_root")
        ptau_path = ptau_root / _safe_relative(str(ptau.get("path", "")), label="PTAU path")
        expected = _expect_hash(ptau.get("sha256"), label="PTAU sha256")
        if not ptau_path.is_file() or ptau_path.is_symlink():
            raise ReleaseError(f"test PTAU is missing or unsafe: {ptau_path}")
        actual_hash = sha256_file(ptau_path)
        if actual_hash != expected:
            raise ReleaseError("test PTAU hash mismatch")
        ptau_record = {
            "path": str(ptau["path"]),
            "sha256": actual_hash,
            "size": ptau_path.stat().st_size,
            "included": False,
            "trust": "test-only",
        }
    manifest: dict[str, Any] = {
        "schema": "waybill-prover-artifact-manifest/v1",
        "bindings": dict(bindings),
        "files": files,
    }
    if ptau_record is not None:
        manifest["test_ptau"] = ptau_record
    return manifest


def write_deterministic_tar(
    output: Path,
    root: Path,
    manifest: Mapping[str, Any],
    *,
    mtime: int,
) -> None:
    """Write a deterministic, regular-file-only prover tar archive."""

    root = root.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
    members: dict[str, tuple[bytes | Path, int, int]] = {
        "artifact-manifest.json": (manifest_bytes, 0o644, len(manifest_bytes))
    }
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ReleaseError("prover manifest files must be an array")
    for record in files:
        if not isinstance(record, dict):
            raise ReleaseError("invalid prover file record")
        path = _safe_relative(str(record.get("path", "")), label="prover archive path")
        source = root / path
        if not source.is_file() or source.is_symlink():
            raise ReleaseError(f"unsafe prover archive source: {source}")
        expected = _expect_hash(record.get("sha256"), label=f"prover file {path}")
        size = source.stat().st_size
        if sha256_file(source) != expected or size != int(record.get("size", -1)):
            raise ReleaseError(f"prover file changed after manifest creation: {path}")
        mode_text = str(record.get("mode", ""))
        if mode_text not in {"0644", "0755"}:
            raise ReleaseError(f"unsafe prover file mode: {path}")
        members[path] = (source, int(mode_text, 8), size)
    with tarfile.open(output, "w", format=tarfile.GNU_FORMAT) as archive:
        for path in sorted(members):
            payload, mode, size = members[path]
            info = tarfile.TarInfo(path)
            info.size = size
            info.mtime = int(mtime)
            info.mode = mode
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            if isinstance(payload, bytes):
                archive.addfile(info, io.BytesIO(payload))
            else:
                with payload.open("rb") as handle:
                    archive.addfile(info, handle)


def _materialize_tar(archive_path: Path, temporary: Path) -> Path:
    if archive_path.name.endswith(".tar.zst"):
        if shutil.which("zstd") is None:
            raise ReleaseError("zstd is required to verify .tar.zst archives")
        output = temporary / "archive.tar"
        try:
            process = subprocess.Popen(
                ("zstd", "--quiet", "--decompress", "--stdout", str(archive_path)),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ReleaseError(f"cannot execute zstd: {exc}") from exc
        total = 0
        assert process.stdout is not None
        stdout = process.stdout
        try:
            with output.open("wb") as handle:
                for chunk in iter(lambda: stdout.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_ZSTD_OUTPUT_BYTES:
                        process.kill()
                        raise ReleaseError("decompressed prover archive exceeds the size limit")
                    handle.write(chunk)
            stderr = b"" if process.stderr is None else process.stderr.read()
            returncode = process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        if returncode != 0:
            raise ReleaseError(stderr.decode("utf-8", errors="replace"))
        return output
    return archive_path


def verify_prover_archive(
    archive_path: Path,
    *,
    expected_bindings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="waybill-prover-verify-") as raw_temp:
        tar_path = _materialize_tar(archive_path, Path(raw_temp))
        try:
            archive = tarfile.open(tar_path, "r:")
        except (tarfile.TarError, OSError) as exc:
            raise ReleaseError(f"invalid prover archive: {exc}") from exc
        with archive:
            members: dict[str, tarfile.TarInfo] = {}
            total_size = 0
            for member_number, member in enumerate(archive, 1):
                if member_number > MAX_ARCHIVE_MEMBERS:
                    raise ReleaseError("prover archive contains too many members")
                path = _safe_relative(member.name, label="tar member")
                if path in members:
                    raise ReleaseError(f"duplicate tar member: {path}")
                if not member.isfile():
                    raise ReleaseError(f"non-regular tar member is forbidden: {path}")
                if member.uid != 0 or member.gid != 0 or member.mode not in {0o644, 0o755}:
                    raise ReleaseError(f"unsafe or non-deterministic tar metadata: {path}")
                if member.pax_headers:
                    raise ReleaseError(f"unexpected extended tar headers: {path}")
                if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ReleaseError(f"prover archive member exceeds the size limit: {path}")
                total_size += member.size
                if total_size > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ReleaseError("prover archive exceeds the total size limit")
                members[path] = member
            manifest_member = members.get("artifact-manifest.json")
            if manifest_member is None:
                raise ReleaseError("prover archive has no artifact-manifest.json")
            handle = archive.extractfile(manifest_member)
            if handle is None:
                raise ReleaseError("cannot read prover artifact manifest")
            manifest_data = handle.read(MAX_JSON_BYTES + 1)
            manifest = _load_json_bytes(manifest_data, label="artifact-manifest.json")
            if manifest.get("schema") != "waybill-prover-artifact-manifest/v1":
                raise ReleaseError("unsupported prover artifact manifest schema")
            if expected_bindings is not None and manifest.get("bindings") != dict(expected_bindings):
                raise ReleaseError("prover archive bindings do not match release")
            records = manifest.get("files")
            if not isinstance(records, list):
                raise ReleaseError("prover manifest files must be an array")
            expected_paths: set[str] = {"artifact-manifest.json"}
            for record in records:
                if not isinstance(record, dict):
                    raise ReleaseError("invalid prover manifest file record")
                path = _safe_relative(str(record.get("path", "")), label="prover file")
                if path in expected_paths:
                    raise ReleaseError(f"duplicate prover manifest path: {path}")
                expected_paths.add(path)
                file_member = members.get(path)
                if file_member is None:
                    raise ReleaseError(f"prover archive is missing {path}")
                handle = archive.extractfile(file_member)
                if handle is None:
                    raise ReleaseError(f"cannot read prover archive member: {path}")
                actual_hash, actual_size = _sha256_stream(
                    handle,
                    label=f"prover archive member {path}",
                )
                expected_hash = _expect_hash(record.get("sha256"), label=f"prover file {path}")
                mode_text = str(record.get("mode", ""))
                if mode_text not in {"0644", "0755"}:
                    raise ReleaseError(f"unsafe prover manifest mode: {path}")
                if (
                    actual_size != int(record.get("size", -1))
                    or actual_hash != expected_hash
                    or file_member.mode != int(mode_text, 8)
                ):
                    raise ReleaseError(f"prover archive file hash/size mismatch: {path}")
            if set(members) != expected_paths:
                raise ReleaseError("prover archive contains unmanifested or missing files")
            return manifest


def create_source_bundle(repo: Path, tag: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(("git", "-C", str(repo), "bundle", "create", str(output), _git_ref(tag)))


@contextmanager
def _source_bundle_repository(
    bundle: Path,
    tag: str,
    expected_identity: Mapping[str, Any],
) -> Any:
    ref = _git_ref(tag)
    heads = _run(("git", "bundle", "list-heads", str(bundle))).decode().splitlines()
    expected_suffix = f" {ref}"
    if len(heads) != 1 or not heads[0].endswith(expected_suffix):
        raise ReleaseError(f"source bundle does not contain exactly one {ref} head")
    with tempfile.TemporaryDirectory(prefix="waybill-bundle-verify-") as raw_temp:
        repo = Path(raw_temp) / "verify.git"
        _run(("git", "init", "--bare", "--quiet", str(repo)))
        _run(("git", "-C", str(repo), "bundle", "verify", str(bundle)))
        _run(("git", "-C", str(repo), "fetch", "--quiet", str(bundle), f"{ref}:{ref}"))
        object_type = run_git(repo, "cat-file", "-t", ref).decode().strip()
        if object_type != "tag":
            raise ReleaseError("bundled release tag is not annotated")
        actual = {
            "tag_object": run_git(repo, "rev-parse", ref).decode().strip(),
            "commit": run_git(repo, "rev-parse", f"{ref}^{{commit}}").decode().strip(),
            "tree": run_git(repo, "rev-parse", f"{ref}^{{tree}}").decode().strip(),
        }
        for key in actual:
            if actual[key] != str(expected_identity[key]):
                raise ReleaseError(f"source bundle {key} mismatch")
        yield repo


def _verify_code_manifest_in_repo(
    repo: Path,
    tag: str,
    expected_identity: Mapping[str, Any],
    code_manifest: Mapping[str, Any],
    config: Mapping[str, Any] | None,
) -> None:
    expected_header = {
        "tag": tag,
        "tag_object": expected_identity.get("tag_object"),
        "git_commit": expected_identity.get("commit"),
        "git_tree": expected_identity.get("tree"),
        "commit_time_epoch": expected_identity.get("commit_time_epoch"),
    }
    for key, expected in expected_header.items():
        if code_manifest.get(key) != expected:
            raise ReleaseError(f"code manifest {key} mismatch")
    records = code_manifest.get("files")
    if not isinstance(records, list) or code_manifest.get("file_count") != len(records):
        raise ReleaseError("code manifest file count is invalid")
    paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReleaseError("invalid code manifest file record")
        path = _safe_relative(str(record.get("path", "")), label="code path")
        if path in paths:
            raise ReleaseError(f"duplicate code manifest path: {path}")
        paths.add(path)
        data = git_blob(repo, tag, path)
        if record.get("sha256") != sha256_bytes(data) or record.get("size") != len(data):
            raise ReleaseError(f"code manifest blob mismatch: {path}")
    entries = _tree_entries(repo, tag, paths)
    for record in records:
        path = str(record["path"])
        if entries.get(path, {}).get("mode") != record.get("mode"):
            raise ReleaseError(f"code manifest mode mismatch: {path}")
    if config is not None:
        expected_paths = set(expand_required_tag_paths(repo, tag, config))
        if paths != expected_paths:
            raise ReleaseError("code manifest path set does not match tagged config")


def verify_source_bundle(
    bundle: Path,
    tag: str,
    expected_identity: Mapping[str, Any],
    *,
    code_manifest: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> None:
    with _source_bundle_repository(bundle, tag, expected_identity) as repo:
        if code_manifest is not None:
            _verify_code_manifest_in_repo(
                repo,
                tag,
                expected_identity,
                code_manifest,
                config,
            )


def verify_image_metadata(
    image_tar: Path,
    metadata: Mapping[str, Any],
    *,
    role: str,
    bindings: Mapping[str, Any],
    platform: str = "linux/amd64",
    user: str,
) -> dict[str, Any]:
    if not image_tar.is_file() or image_tar.is_symlink():
        raise ReleaseError(f"container image tar is missing or unsafe: {image_tar}")
    if metadata.get("schema") != "waybill-container-image-metadata/v2":
        raise ReleaseError("unsupported container image metadata schema")
    if metadata.get("role") != role or metadata.get("platform") != platform:
        raise ReleaseError(f"container metadata role/platform mismatch: {role}")
    if not isinstance(metadata.get("image_ref"), str) or not metadata["image_ref"].strip():
        raise ReleaseError(f"container metadata has no image reference: {role}")
    derived = _verify_container_image_archive(image_tar)
    for key in ("image_digest", "config_digest"):
        if not DIGEST_RE.fullmatch(str(metadata.get(key, ""))):
            raise ReleaseError(f"container metadata has invalid {key}: {role}")
        if metadata.get(key) != derived[key]:
            raise ReleaseError(f"container metadata {key} is not derived from the archive: {role}")
    if metadata.get("archive_format") != derived["archive_format"]:
        raise ReleaseError(f"container metadata archive format mismatch: {role}")
    if metadata.get("platform") != derived["platform"]:
        raise ReleaseError(f"container archive platform mismatch: {role}")
    if metadata.get("user") != derived["user"] or derived["user"] != user:
        raise ReleaseError(f"container archive runtime user mismatch: {role}")
    if metadata["image_ref"] not in derived["image_refs"]:
        raise ReleaseError(f"container image reference is absent from the archive: {role}")
    actual_tar_hash = sha256_file(image_tar)
    if metadata.get("image_tar_sha256") != actual_tar_hash:
        raise ReleaseError(f"container image tar hash mismatch: {role}")
    if metadata.get("bindings") != dict(bindings):
        raise ReleaseError(f"container image source bindings mismatch: {role}")
    labels = derived["labels"]
    for label, binding_key in CONTAINER_BINDING_LABELS.items():
        if labels.get(label) != str(bindings.get(binding_key, "")):
            raise ReleaseError(f"container image binding label mismatch: {role}:{label}")
    return dict(metadata)


def _verify_container_image_archive(path: Path) -> dict[str, Any]:
    """Verify Docker-save/OCI descriptors and derive immutable image identity."""

    try:
        archive = tarfile.open(path, "r:*")
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseError(f"invalid container image tar: {path}") from exc
    with archive:
        members: dict[str, tarfile.TarInfo] = {}
        total_size = 0
        for member_number, member in enumerate(archive, 1):
            if member_number > MAX_ARCHIVE_MEMBERS:
                raise ReleaseError("container image archive contains too many members")
            raw_name = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
            name = _safe_relative(raw_name, label="container tar member")
            if name in members:
                raise ReleaseError(f"duplicate container tar member: {name}")
            if not (member.isfile() or member.isdir()):
                raise ReleaseError(f"unsafe container tar member: {name}")
            if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                raise ReleaseError(f"container archive member exceeds the size limit: {name}")
            total_size += member.size
            if total_size > MAX_ARCHIVE_TOTAL_BYTES:
                raise ReleaseError("container image archive exceeds the total size limit")
            members[name] = member

        def member_bytes(name: str, *, max_bytes: int = MAX_ARCHIVE_MEMBER_BYTES) -> bytes:
            member = members.get(name)
            if member is None or not member.isfile():
                raise ReleaseError(f"container image archive is missing {name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise ReleaseError(f"cannot read container image archive member: {name}")
            data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ReleaseError(f"container archive member exceeds the read limit: {name}")
            return data

        def load_member_json(name: str) -> Any:
            return _load_json_value(member_bytes(name, max_bytes=MAX_JSON_BYTES), label=name)

        def descriptor_blob(descriptor: Any, *, label: str) -> tuple[str, bytes]:
            if not isinstance(descriptor, dict):
                raise ReleaseError(f"invalid OCI descriptor: {label}")
            digest = str(descriptor.get("digest", ""))
            if not DIGEST_RE.fullmatch(digest):
                raise ReleaseError(f"invalid OCI descriptor digest: {label}")
            blob_path = f"blobs/sha256/{digest.removeprefix('sha256:')}"
            data = member_bytes(blob_path)
            if sha256_bytes(data) != digest.removeprefix("sha256:"):
                raise ReleaseError(f"OCI descriptor digest mismatch: {label}")
            if descriptor.get("size") != len(data):
                raise ReleaseError(f"OCI descriptor size mismatch: {label}")
            return digest, data

        def image_configuration(
            config: Any,
            *,
            label: str,
        ) -> tuple[str, dict[str, str], str]:
            if not isinstance(config, dict):
                raise ReleaseError(f"container image config must be an object: {label}")
            os_name = config.get("os")
            architecture = config.get("architecture")
            if not isinstance(os_name, str) or not isinstance(architecture, str):
                raise ReleaseError(f"container image config has no platform: {label}")
            config_section = config.get("config")
            labels = config_section.get("Labels") if isinstance(config_section, dict) else None
            if not isinstance(labels, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in labels.items()
            ):
                raise ReleaseError(f"container image has no valid OCI label map: {label}")
            user = config_section.get("User") if isinstance(config_section, dict) else None
            if not isinstance(user, str) or re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", user) is None:
                raise ReleaseError(f"container image must declare a fixed non-root UID:GID: {label}")
            return f"{os_name}/{architecture}", dict(labels), user

        if "manifest.json" in members and not (
            "oci-layout" in members and "index.json" in members
        ):
            manifest = load_member_json("manifest.json")
            if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
                raise ReleaseError("Docker image manifest.json must describe exactly one image")
            record = manifest[0]
            config_path = _safe_relative(str(record.get("Config", "")), label="Docker config")
            config_blob = member_bytes(config_path, max_bytes=MAX_JSON_BYTES)
            config_sha256 = sha256_bytes(config_blob)
            if PurePosixPath(config_path).name != f"{config_sha256}.json":
                raise ReleaseError("Docker config filename is not its SHA-256 image ID")
            config = _load_json_bytes(config_blob, label=config_path)
            platform_value, labels, user = image_configuration(config, label=config_path)
            layers = record.get("Layers")
            if not isinstance(layers, list) or not layers or not all(
                isinstance(item, str) for item in layers
            ):
                raise ReleaseError("Docker image manifest has no valid layer list")
            layer_paths = [
                _safe_relative(item, label="Docker layer path") for item in layers
            ]
            rootfs = config.get("rootfs")
            diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
            if not isinstance(diff_ids, list) or len(diff_ids) != len(layer_paths):
                raise ReleaseError("Docker image rootfs.diff_ids does not match its layers")
            for layer_path, expected_diff_id in zip(layer_paths, diff_ids):
                if not DIGEST_RE.fullmatch(str(expected_diff_id)):
                    raise ReleaseError(f"invalid Docker layer diff ID: {layer_path}")
                layer_member = members.get(layer_path)
                if layer_member is None or not layer_member.isfile():
                    raise ReleaseError(f"Docker image archive is missing layer: {layer_path}")
                handle = archive.extractfile(layer_member)
                if handle is None:
                    raise ReleaseError(f"cannot read Docker image layer: {layer_path}")
                actual_hash, actual_size = _sha256_stream(
                    handle,
                    label=f"Docker layer {layer_path}",
                )
                if actual_size != layer_member.size or f"sha256:{actual_hash}" != expected_diff_id:
                    raise ReleaseError(f"Docker layer digest/size mismatch: {layer_path}")
            repo_tags = record.get("RepoTags")
            if not isinstance(repo_tags, list) or not repo_tags or not all(
                isinstance(item, str) and item.strip() for item in repo_tags
            ):
                raise ReleaseError("Docker image manifest has no repository tag")
            config_digest = f"sha256:{config_sha256}"
            return {
                "archive_format": "docker-save",
                "image_digest": config_digest,
                "config_digest": config_digest,
                "layers": layer_paths,
                "platform": platform_value,
                "image_refs": list(repo_tags),
                "labels": labels,
                "user": user,
            }
        if "oci-layout" in members and "index.json" in members:
            layout = load_member_json("oci-layout")
            index = load_member_json("index.json")
            if not isinstance(layout, dict) or layout.get("imageLayoutVersion") != "1.0.0":
                raise ReleaseError("unsupported OCI image layout version")
            if not isinstance(index, dict) or not isinstance(index.get("manifests"), list):
                raise ReleaseError("invalid OCI image index")
            if len(index["manifests"]) != 1:
                raise ReleaseError("OCI image index must describe exactly one image")
            image_descriptor = index["manifests"][0]
            image_digest, manifest_blob = descriptor_blob(
                image_descriptor,
                label="image manifest",
            )
            image_manifest = _load_json_bytes(manifest_blob, label="OCI image manifest")
            if image_manifest.get("schemaVersion") != 2:
                raise ReleaseError("unsupported OCI image manifest schema")
            config_digest, config_blob = descriptor_blob(
                image_manifest.get("config"),
                label="image config",
            )
            config = _load_json_bytes(config_blob, label="OCI image config")
            platform_value, labels, user = image_configuration(config, label="OCI image config")
            descriptor_platform = (
                image_descriptor.get("platform") if isinstance(image_descriptor, dict) else None
            )
            if descriptor_platform is not None:
                if not isinstance(descriptor_platform, dict) or (
                    f"{descriptor_platform.get('os')}/{descriptor_platform.get('architecture')}"
                    != platform_value
                ):
                    raise ReleaseError("OCI index platform does not match the image config")
            layers = image_manifest.get("layers")
            if not isinstance(layers, list) or not layers:
                raise ReleaseError("OCI image manifest contains no layers")
            oci_layer_paths: list[str] = []
            for index_number, layer in enumerate(layers):
                layer_digest, _ = descriptor_blob(layer, label=f"layer {index_number}")
                oci_layer_paths.append(
                    f"blobs/sha256/{layer_digest.removeprefix('sha256:')}"
                )
            annotations = image_descriptor.get("annotations")
            image_refs: set[str] = set()
            if isinstance(annotations, dict):
                for annotation in (
                    "org.opencontainers.image.ref.name",
                    "io.containerd.image.name",
                ):
                    value = annotations.get(annotation)
                    if isinstance(value, str) and value.strip():
                        image_refs.add(value)
                        if value.startswith("docker.io/library/"):
                            image_refs.add(value.removeprefix("docker.io/library/"))
            if "manifest.json" in members:
                docker_manifest = load_member_json("manifest.json")
                if (
                    not isinstance(docker_manifest, list)
                    or len(docker_manifest) != 1
                    or not isinstance(docker_manifest[0], dict)
                ):
                    raise ReleaseError("Docker compatibility manifest is invalid")
                docker_record = docker_manifest[0]
                expected_config_path = (
                    f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
                )
                if docker_record.get("Config") != expected_config_path:
                    raise ReleaseError("Docker/OCI config descriptors do not match")
                if docker_record.get("Layers") != oci_layer_paths:
                    raise ReleaseError("Docker/OCI layer descriptors do not match")
                repo_tags = docker_record.get("RepoTags")
                if not isinstance(repo_tags, list) or not repo_tags or not all(
                    isinstance(item, str) and item.strip() for item in repo_tags
                ):
                    raise ReleaseError("Docker compatibility manifest has no repository tag")
                image_refs.update(repo_tags)
            if not image_refs:
                raise ReleaseError("OCI image descriptor has no image reference")
            return {
                "archive_format": "oci-layout",
                "image_digest": image_digest,
                "config_digest": config_digest,
                "layers": oci_layer_paths,
                "platform": platform_value,
                "image_refs": sorted(image_refs),
                "labels": labels,
                "user": user,
            }
        raise ReleaseError("container tar is neither Docker-save nor OCI-layout format")


def verify_formal_runner_embedded_source(
    image_tar: Path,
    *,
    code_manifest: Mapping[str, Any],
    config: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct `/work` from image layers and compare it with tagged blobs."""

    containers = config.get("containers")
    roles = containers.get("roles") if isinstance(containers, dict) else None
    formal = roles.get("formal-runner") if isinstance(roles, dict) else None
    raw_prefixes = formal.get("embedded_source_paths") if isinstance(formal, dict) else None
    if not isinstance(raw_prefixes, list) or not raw_prefixes:
        raise ReleaseError("formal-runner embedded_source_paths must be a non-empty array")
    prefixes = [
        _safe_relative(str(raw), label="formal embedded source path")
        for raw in raw_prefixes
    ]
    if len(prefixes) != len(set(prefixes)):
        raise ReleaseError("formal-runner embedded source paths contain duplicates")
    records = code_manifest.get("files")
    if not isinstance(records, list):
        raise ReleaseError("release code manifest file ledger is missing")
    expected: dict[str, dict[str, Any]] = {}
    matched_prefixes: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReleaseError("release code manifest contains an invalid file record")
        path = _safe_relative(str(record.get("path", "")), label="embedded code path")
        matching = [
            prefix
            for prefix in prefixes
            if path == prefix or path.startswith(f"{prefix.rstrip('/')}/")
        ]
        if not matching:
            continue
        matched_prefixes.update(matching)
        expected[f"work/{path}"] = dict(record)
    if matched_prefixes != set(prefixes) or not expected:
        raise ReleaseError("formal-runner embedded source paths do not match tagged code files")

    derived = _verify_container_image_archive(image_tar)
    layer_paths = derived.get("layers")
    if not isinstance(layer_paths, list) or not layer_paths:
        raise ReleaseError("formal-runner image has no verified layer sequence")
    try:
        outer = tarfile.open(image_tar, "r:*")
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseError(f"invalid formal-runner image tar: {image_tar}") from exc
    visible: dict[str, dict[str, Any]] = {}

    def drop(path: str) -> None:
        for existing in list(visible):
            if existing == path or existing.startswith(f"{path.rstrip('/')}/"):
                visible.pop(existing, None)

    with outer:
        outer_members = {member.name: member for member in outer.getmembers()}
        for layer_path in layer_paths:
            layer_member = outer_members.get(str(layer_path))
            if layer_member is None or not layer_member.isfile():
                raise ReleaseError(f"formal-runner layer is missing: {layer_path}")
            layer_handle = outer.extractfile(layer_member)
            if layer_handle is None:
                raise ReleaseError(f"cannot read formal-runner layer: {layer_path}")
            try:
                layer = tarfile.open(fileobj=layer_handle, mode="r|*")
            except tarfile.TarError as exc:
                raise ReleaseError(f"formal-runner layer is not a tar archive: {layer_path}") from exc
            with layer:
                for member in layer:
                    raw_name = member.name
                    while raw_name.startswith("./"):
                        raw_name = raw_name[2:]
                    if raw_name in {"", "."}:
                        continue
                    name = _safe_relative(raw_name.rstrip("/"), label="image filesystem path")
                    pure = PurePosixPath(name)
                    basename = pure.name
                    parent = pure.parent.as_posix()
                    if basename == ".wh..wh..opq":
                        if parent == ".":
                            visible.clear()
                        else:
                            drop(parent)
                        continue
                    if basename.startswith(".wh."):
                        target_name = basename.removeprefix(".wh.")
                        target = target_name if parent == "." else f"{parent}/{target_name}"
                        drop(target)
                        continue
                    tracked = name == "opt/waybill/release-bindings.json" or name.startswith(
                        "work/"
                    )
                    if not tracked:
                        continue
                    if member.isdir():
                        visible.pop(name, None)
                        continue
                    if not member.isfile():
                        raise ReleaseError(f"formal-runner source contains a non-regular path: {name}")
                    if member.size < 0 or member.size > 64 * 1024 * 1024:
                        raise ReleaseError(f"formal-runner source file is too large: {name}")
                    handle = layer.extractfile(member)
                    if handle is None:
                        raise ReleaseError(f"cannot read formal-runner source file: {name}")
                    data = handle.read(member.size + 1)
                    if len(data) != member.size:
                        raise ReleaseError(f"formal-runner source file size mismatch: {name}")
                    drop(name)
                    visible[name] = {
                        "size": len(data),
                        "sha256": sha256_bytes(data),
                        "mode": member.mode & 0o777,
                        "data": data if name == "opt/waybill/release-bindings.json" else None,
                    }

    actual_work = {path: record for path, record in visible.items() if path.startswith("work/")}
    if set(actual_work) != set(expected):
        missing = sorted(set(expected) - set(actual_work))
        extra = sorted(set(actual_work) - set(expected))
        raise ReleaseError(
            f"formal-runner embedded source file set mismatch; missing={missing}, extra={extra}"
        )
    for image_path, expected_record in expected.items():
        actual = actual_work[image_path]
        expected_mode = str(expected_record.get("mode", ""))
        if expected_mode not in {"100644", "100755"}:
            raise ReleaseError(f"invalid tagged embedded source mode: {image_path}")
        if (
            actual["size"] != expected_record.get("size")
            or actual["sha256"] != expected_record.get("sha256")
            or actual["mode"] != int(expected_mode[-3:], 8)
        ):
            raise ReleaseError(f"formal-runner embedded source blob mismatch: {image_path}")
    binding_record = visible.get("opt/waybill/release-bindings.json")
    if not isinstance(binding_record, dict) or not isinstance(binding_record.get("data"), bytes):
        raise ReleaseError("formal-runner embedded release binding file is missing")
    embedded_binding = _load_json_bytes(
        binding_record["data"],
        label="formal-runner embedded release binding",
    )
    expected_binding = {
        "schema": "waybill.formal.embedded-release-binding/v1",
        **dict(bindings),
    }
    if embedded_binding != expected_binding or binding_record.get("mode") != 0o444:
        raise ReleaseError("formal-runner embedded release binding mismatch")
    return {
        "schema": "waybill-formal-embedded-source-verification/v1",
        "file_count": len(expected),
        "files_sha256": canonical_sha256(
            [
                {
                    "path": path,
                    "size": expected[path]["size"],
                    "sha256": expected[path]["sha256"],
                    "mode": expected[path]["mode"],
                }
                for path in sorted(expected)
            ]
        ),
        "release_binding": embedded_binding,
    }


def verify_sbom(
    path: Path,
    *,
    role: str,
    image_metadata: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    sbom = _load_json_bytes(path.read_bytes(), label=str(path))
    return _verify_sbom_value(
        sbom,
        role=role,
        image_metadata=image_metadata,
        bindings=bindings,
    )


def _verify_sbom_value(
    sbom: dict[str, Any],
    *,
    role: str,
    image_metadata: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    if sbom.get("spdxVersion") != "SPDX-2.3":
        raise ReleaseError(f"SBOM is not SPDX JSON: {role}")
    if sbom.get("SPDXID") != "SPDXRef-DOCUMENT" or sbom.get("dataLicense") != "CC0-1.0":
        raise ReleaseError(f"SBOM document identity/license is invalid: {role}")
    if not isinstance(sbom.get("documentNamespace"), str) or not sbom["documentNamespace"].strip():
        raise ReleaseError(f"SBOM document namespace is missing: {role}")
    creation = sbom.get("creationInfo")
    if not isinstance(creation, dict) or not isinstance(creation.get("creators"), list) or not creation[
        "creators"
    ]:
        raise ReleaseError(f"SBOM creation provenance is missing: {role}")
    packages = sbom.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ReleaseError(f"SBOM contains no packages: {role}")
    package_ids = {
        package.get("SPDXID")
        for package in packages
        if isinstance(package, dict) and isinstance(package.get("SPDXID"), str)
    }
    if len(package_ids) != len(packages):
        raise ReleaseError(f"SBOM package identifiers are missing or duplicated: {role}")
    described_ids: set[str] = set()
    described = sbom.get("documentDescribes")
    if described is not None:
        if not isinstance(described, list) or any(
            not isinstance(identifier, str) for identifier in described
        ):
            raise ReleaseError(f"SBOM documentDescribes is invalid: {role}")
        described_ids.update(described)
    relationships = sbom.get("relationships", [])
    if relationships is None:
        relationships = []
    if not isinstance(relationships, list):
        raise ReleaseError(f"SBOM relationships are invalid: {role}")
    for relationship in relationships:
        if not isinstance(relationship, dict):
            raise ReleaseError(f"SBOM relationship record is invalid: {role}")
        if (
            relationship.get("spdxElementId") == "SPDXRef-DOCUMENT"
            and relationship.get("relationshipType") == "DESCRIBES"
            and isinstance(relationship.get("relatedSpdxElement"), str)
        ):
            described_ids.add(relationship["relatedSpdxElement"])
    if not described_ids or not described_ids.issubset(package_ids):
        raise ReleaseError(f"SBOM documentDescribes is not bound to a package: {role}")
    expected = {
        "role": role,
        "image_digest": image_metadata["image_digest"],
        "image_tar_sha256": image_metadata["image_tar_sha256"],
        **dict(bindings),
    }
    if sbom.get("waybillBinding") != expected:
        raise ReleaseError(f"SBOM binding mismatch: {role}")
    return sbom


def release_bindings_from_preflight(preflight: Mapping[str, Any]) -> dict[str, str]:
    if preflight.get("schema") != "waybill-release-preflight/v2":
        raise ReleaseError("unsupported release preflight schema")
    identity = preflight.get("identity")
    protocol = preflight.get("protocol")
    if not isinstance(identity, dict) or not isinstance(protocol, dict):
        raise ReleaseError("release preflight identity/protocol is invalid")
    bindings = {
        "git_commit": str(identity.get("commit", "")),
        "git_tree": str(identity.get("tree", "")),
        "code_manifest_sha256": str(preflight.get("code_manifest_sha256", "")),
        "protocol_sha256": str(protocol.get("canonical_sha256", "")),
    }
    if not re.fullmatch(r"[0-9a-f]{40,64}", bindings["git_commit"]):
        raise ReleaseError("release preflight Git commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{40,64}", bindings["git_tree"]):
        raise ReleaseError("release preflight Git tree is invalid")
    for name in ("code_manifest_sha256", "protocol_sha256"):
        if SHA256_RE.fullmatch(bindings[name]) is None:
            raise ReleaseError(f"release preflight {name} is invalid")
    return bindings


def create_image_metadata(
    *,
    image_tar: Path,
    role: str,
    image_ref: str,
    config: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    roles = _configured_container_roles(config)
    if role not in roles:
        raise ReleaseError(f"container role is not configured: {role}")
    bindings = release_bindings_from_preflight(preflight)
    derived = _verify_container_image_archive(image_tar)
    if image_ref not in derived["image_refs"]:
        raise ReleaseError(f"container image reference is absent from the archive: {role}")
    metadata = {
        "schema": "waybill-container-image-metadata/v2",
        "role": role,
        "platform": derived["platform"],
        "user": derived["user"],
        "archive_format": derived["archive_format"],
        "image_ref": image_ref,
        "image_digest": derived["image_digest"],
        "config_digest": derived["config_digest"],
        "image_tar_sha256": sha256_file(image_tar),
        "bindings": bindings,
    }
    return verify_image_metadata(
        image_tar,
        metadata,
        role=role,
        bindings=bindings,
        platform=roles[role]["platform"],
        user=roles[role]["user"],
    )


def bind_scanner_sbom(
    *,
    raw_sbom_path: Path,
    metadata_path: Path,
    role: str,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    sbom = _load_json_bytes(raw_sbom_path.read_bytes(), label=str(raw_sbom_path))
    if "waybillBinding" in sbom:
        raise ReleaseError("raw scanner SBOM already contains a WayBill binding")
    metadata = _load_json_bytes(metadata_path.read_bytes(), label=str(metadata_path))
    if metadata.get("role") != role:
        raise ReleaseError("SBOM role does not match the image metadata")
    bindings = release_bindings_from_preflight(preflight)
    if metadata.get("bindings") != bindings:
        raise ReleaseError("image metadata does not match the release preflight")
    sbom["waybillBinding"] = {
        "role": role,
        "image_digest": metadata.get("image_digest"),
        "image_tar_sha256": metadata.get("image_tar_sha256"),
        **bindings,
    }
    return _verify_sbom_value(
        sbom,
        role=role,
        image_metadata=metadata,
        bindings=bindings,
    )


def _configured_vulnerability_scanner(config: Mapping[str, Any]) -> dict[str, Any]:
    containers = config.get("containers")
    scanner = containers.get("scanner") if isinstance(containers, dict) else None
    if not isinstance(scanner, dict):
        raise ReleaseError("config.containers.scanner must be an object")
    if scanner.get("name") != "trivy":
        raise ReleaseError("config.containers.scanner.name must be trivy")
    version = scanner.get("version")
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ReleaseError("config.containers.scanner.version must be an exact version")
    report_schema_version = scanner.get("report_schema_version")
    if isinstance(report_schema_version, bool) or report_schema_version != 2:
        raise ReleaseError("config.containers.scanner.report_schema_version must be 2")
    return {
        "name": "trivy",
        "version": version,
        "report_schema_version": report_schema_version,
    }


def _configured_vulnerability_policy(
    config: Mapping[str, Any], role: str
) -> dict[str, Any]:
    containers = config.get("containers")
    roles = containers.get("roles") if isinstance(containers, dict) else None
    settings = roles.get(role) if isinstance(roles, dict) else None
    policy = settings.get("vulnerability_policy") if isinstance(settings, dict) else None
    if not isinstance(policy, dict):
        raise ReleaseError(f"container vulnerability policy is missing: {role}")
    maximum = policy.get("max_high_critical")
    max_fixable = policy.get("max_fixable_high_critical")
    max_fixable_total = policy.get("max_fixable")
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum < 0
        or isinstance(max_fixable, bool)
        or not isinstance(max_fixable, int)
        or max_fixable < 0
        or max_fixable > maximum
        or isinstance(max_fixable_total, bool)
        or not isinstance(max_fixable_total, int)
        or max_fixable_total < 0
        or max_fixable > max_fixable_total
    ):
        raise ReleaseError(f"container vulnerability thresholds are invalid: {role}")
    allowed = policy.get("allowed_unfixed_high_critical_ids")
    if not isinstance(allowed, list):
        raise ReleaseError(f"container vulnerability allowlist is invalid: {role}")
    normalized: list[str] = []
    for raw_identifier in allowed:
        identifier = str(raw_identifier)
        if re.fullmatch(r"[A-Z0-9][A-Z0-9._:-]{2,127}", identifier) is None:
            raise ReleaseError(f"invalid vulnerability identifier for {role}: {identifier!r}")
        normalized.append(identifier)
    if len(set(normalized)) != len(normalized):
        raise ReleaseError(f"duplicate vulnerability allowlist identifier: {role}")
    return {
        "max_high_critical": maximum,
        "max_fixable": max_fixable_total,
        "max_fixable_high_critical": max_fixable,
        "allowed_unfixed_high_critical_ids": sorted(normalized),
    }


def _vulnerability_summary(report: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ReleaseError(f"Trivy vulnerability report contains no scan results: {role}")
    high = 0
    critical = 0
    fixable = 0
    fixable_by_severity = {
        "CRITICAL": 0,
        "HIGH": 0,
        "LOW": 0,
        "MEDIUM": 0,
        "UNKNOWN": 0,
    }
    unfixed_ids: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ReleaseError(f"Trivy vulnerability result is invalid: {role}")
        vulnerabilities = result.get("Vulnerabilities", [])
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities, list):
            raise ReleaseError(f"Trivy vulnerabilities must be an array: {role}")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise ReleaseError(f"Trivy vulnerability record is invalid: {role}")
            identifier = vulnerability.get("VulnerabilityID")
            severity = vulnerability.get("Severity")
            if not isinstance(identifier, str) or not identifier.strip():
                raise ReleaseError(f"Trivy vulnerability identifier is missing: {role}")
            if severity not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ReleaseError(f"Trivy vulnerability severity is invalid: {role}")
            fixed_version = vulnerability.get("FixedVersion", "")
            if fixed_version is None:
                fixed_version = ""
            if not isinstance(fixed_version, str):
                raise ReleaseError(f"Trivy FixedVersion is invalid: {role}")
            is_fixable = bool(fixed_version.strip())
            if is_fixable:
                fixable_by_severity[severity] += 1
            if severity not in {"HIGH", "CRITICAL"}:
                continue
            if severity == "HIGH":
                high += 1
            else:
                critical += 1
            if is_fixable:
                fixable += 1
            else:
                unfixed_ids.add(identifier)
    return {
        "critical": critical,
        "fixable_by_severity": fixable_by_severity,
        "fixable_high_critical": fixable,
        "fixable_total": sum(fixable_by_severity.values()),
        "high": high,
        "total_high_critical": high + critical,
        "unfixed_high_critical_ids": sorted(unfixed_ids),
    }


def _verify_vulnerability_report_value(
    report: dict[str, Any],
    *,
    role: str,
    image_metadata: Mapping[str, Any],
    bindings: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    scanner = _configured_vulnerability_scanner(config)
    policy = _configured_vulnerability_policy(config, role)
    if report.get("SchemaVersion") != scanner["report_schema_version"]:
        raise ReleaseError(f"unsupported Trivy report schema: {role}")
    trivy = report.get("Trivy")
    if not isinstance(trivy, dict) or trivy.get("Version") != scanner["version"]:
        raise ReleaseError(f"Trivy scanner version mismatch: {role}")
    if report.get("ArtifactType") != "container_image":
        raise ReleaseError(f"Trivy report is not for a container image: {role}")
    for field in ("ReportID", "CreatedAt", "ArtifactName"):
        if not isinstance(report.get(field), str) or not report[field].strip():
            raise ReleaseError(f"Trivy report field is missing ({field}): {role}")
    if DIGEST_RE.fullmatch(str(report.get("ArtifactID", ""))) is None:
        raise ReleaseError(f"Trivy ArtifactID is invalid: {role}")
    metadata = report.get("Metadata")
    if not isinstance(metadata, dict):
        raise ReleaseError(f"Trivy image metadata is missing: {role}")
    scan_image_id = str(metadata.get("ImageID", ""))
    expected_image_ids = {
        str(image_metadata.get("image_digest", "")),
        str(image_metadata.get("config_digest", "")),
    }
    if scan_image_id not in expected_image_ids:
        raise ReleaseError(f"Trivy report image ID mismatch: {role}")
    image_ref = str(image_metadata.get("image_ref", ""))
    repo_tags = metadata.get("RepoTags", [])
    if repo_tags is None:
        repo_tags = []
    if not isinstance(repo_tags, list) or any(not isinstance(tag, str) for tag in repo_tags):
        raise ReleaseError(f"Trivy RepoTags are invalid: {role}")
    if image_ref not in {
        str(report.get("ArtifactName", "")),
        str(metadata.get("Reference", "")),
        *repo_tags,
    }:
        raise ReleaseError(f"Trivy report image reference mismatch: {role}")
    summary = _vulnerability_summary(report, role=role)
    if summary["fixable_total"] > policy["max_fixable"]:
        raise ReleaseError(f"Trivy fixable vulnerability threshold exceeded: {role}")
    if summary["total_high_critical"] > policy["max_high_critical"]:
        raise ReleaseError(f"Trivy HIGH/CRITICAL threshold exceeded: {role}")
    if summary["fixable_high_critical"] > policy["max_fixable_high_critical"]:
        raise ReleaseError(f"Trivy fixable HIGH/CRITICAL threshold exceeded: {role}")
    unexpected = set(summary["unfixed_high_critical_ids"]) - set(
        policy["allowed_unfixed_high_critical_ids"]
    )
    if unexpected:
        raise ReleaseError(
            f"Trivy report contains unapproved unfixed HIGH/CRITICAL findings for {role}: "
            + ", ".join(sorted(unexpected))
        )
    expected_binding = {
        "role": role,
        "image_digest": image_metadata["image_digest"],
        "image_tar_sha256": image_metadata["image_tar_sha256"],
        "scan_image_id": scan_image_id,
        "scanner": scanner,
        "summary": summary,
        **dict(bindings),
    }
    if report.get("waybillBinding") != expected_binding:
        raise ReleaseError(f"Trivy vulnerability report binding mismatch: {role}")
    return report


def verify_vulnerability_report(
    path: Path,
    *,
    role: str,
    image_metadata: Mapping[str, Any],
    bindings: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    report = _load_json_bytes(path.read_bytes(), label=str(path))
    return _verify_vulnerability_report_value(
        report,
        role=role,
        image_metadata=image_metadata,
        bindings=bindings,
        config=config,
    )


def bind_scanner_vulnerability_report(
    *,
    raw_report_path: Path,
    metadata_path: Path,
    role: str,
    preflight: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    report = _load_json_bytes(raw_report_path.read_bytes(), label=str(raw_report_path))
    if "waybillBinding" in report:
        raise ReleaseError("raw Trivy report already contains a WayBill binding")
    metadata = _load_json_bytes(metadata_path.read_bytes(), label=str(metadata_path))
    if metadata.get("role") != role:
        raise ReleaseError("Trivy report role does not match the image metadata")
    bindings = release_bindings_from_preflight(preflight)
    if metadata.get("bindings") != bindings:
        raise ReleaseError("image metadata does not match the release preflight")
    scanner = _configured_vulnerability_scanner(config)
    summary = _vulnerability_summary(report, role=role)
    report_metadata = report.get("Metadata")
    scan_image_id = (
        str(report_metadata.get("ImageID", "")) if isinstance(report_metadata, dict) else ""
    )
    report["waybillBinding"] = {
        "role": role,
        "image_digest": metadata.get("image_digest"),
        "image_tar_sha256": metadata.get("image_tar_sha256"),
        "scan_image_id": scan_image_id,
        "scanner": scanner,
        "summary": summary,
        **bindings,
    }
    return _verify_vulnerability_report_value(
        report,
        role=role,
        image_metadata=metadata,
        bindings=bindings,
        config=config,
    )


def write_sha256sums(release_dir: Path) -> None:
    output = release_dir / "SHA256SUMS"
    paths = sorted(
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("*")
        if path.is_file() and path != output and not path.is_symlink()
    )
    output.write_text(
        "".join(f"{sha256_file(release_dir / path)}  {path}\n" for path in paths),
        encoding="utf-8",
    )


def verify_release_inventory(release_dir: Path) -> dict[str, Any]:
    if not release_dir.is_dir():
        raise ReleaseError(f"release directory does not exist: {release_dir}")
    symlinks = [path for path in release_dir.rglob("*") if path.is_symlink()]
    if symlinks:
        raise ReleaseError(f"release contains symlink: {symlinks[0]}")
    sums_path = release_dir / "SHA256SUMS"
    manifest_path = release_dir / "release-manifest.json"
    if not sums_path.is_file() or not manifest_path.is_file():
        raise ReleaseError("release is missing SHA256SUMS or release-manifest.json")
    declared: dict[str, str] = {}
    for line_number, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise ReleaseError(f"invalid SHA256SUMS line {line_number}")
        digest, raw_path = match.groups()
        path = _safe_relative(raw_path, label="checksum path")
        if path == "SHA256SUMS" or path in declared:
            raise ReleaseError(f"duplicate or recursive checksum path: {path}")
        declared[path] = digest
    actual = {
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("*")
        if path.is_file() and path != sums_path
    }
    if actual != set(declared):
        missing = sorted(actual - set(declared))
        extra = sorted(set(declared) - actual)
        raise ReleaseError(f"release checksum inventory mismatch; missing={missing}, extra={extra}")
    for path, expected in declared.items():
        if sha256_file(release_dir / path) != expected:
            raise ReleaseError(f"release checksum mismatch: {path}")
    manifest = _load_json_bytes(manifest_path.read_bytes(), label="release-manifest.json")
    if manifest.get("schema") != "waybill-formal-release-manifest/v2":
        raise ReleaseError("unsupported release manifest schema")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise ReleaseError("release manifest assets must be an array")
    records: dict[str, dict[str, Any]] = {}
    for record in assets:
        if not isinstance(record, dict):
            raise ReleaseError("invalid release asset record")
        path = _safe_relative(str(record.get("path", "")), label="release asset")
        if path in records:
            raise ReleaseError(f"duplicate release asset: {path}")
        records[path] = record
    expected_assets = actual - {"release-manifest.json"}
    if set(records) != expected_assets:
        raise ReleaseError("release manifest has extra or missing assets")
    for path, record in records.items():
        asset = release_dir / path
        if record.get("sha256") != sha256_file(asset) or record.get("size") != asset.stat().st_size:
            raise ReleaseError(f"release manifest asset mismatch: {path}")
    return manifest


def _preflight(
    repo: Path,
    tag: str,
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    identity = git_release_identity(repo, tag)
    verify_tagged_config(repo, tag, config)
    verify_release_blockers(config)
    code_manifest = build_code_manifest(repo, tag, config, identity=identity)
    receipt_bindings = verify_profile_and_receipts(repo, tag, config)
    protocol = protocol_binding(repo, tag, config)
    return identity, code_manifest, receipt_bindings, protocol


def _copy_regular(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise ReleaseError(f"release input is missing or unsafe: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _release_assets(release_dir: Path) -> list[dict[str, Any]]:
    return [
        {"path": path.relative_to(release_dir).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(release_dir.rglob("*"))
        if path.is_file() and path.name not in {"release-manifest.json", "SHA256SUMS"}
    ]


def _configured_container_roles(config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    section = config.get("containers")
    roles = section.get("roles") if isinstance(section, dict) else None
    if not isinstance(roles, dict) or not roles:
        raise ReleaseError("config.containers.roles must be a non-empty object")
    _configured_vulnerability_scanner(config)
    if "receiver-signer" not in roles:
        raise ReleaseError("config.containers.roles must include the independent receiver-signer")
    normalized: dict[str, dict[str, str]] = {}
    for raw_role, raw_settings in roles.items():
        role = str(raw_role)
        if ROLE_RE.fullmatch(role) is None:
            raise ReleaseError(f"invalid container role: {role!r}")
        if not isinstance(raw_settings, dict):
            raise ReleaseError(f"container role settings must be an object: {role}")
        platform = raw_settings.get("platform")
        if not isinstance(platform, str) or re.fullmatch(r"[a-z0-9_]+/[a-z0-9_]+", platform) is None:
            raise ReleaseError(f"invalid container platform for role: {role}")
        user = raw_settings.get("user")
        if not isinstance(user, str) or re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", user) is None:
            raise ReleaseError(f"container role must pin a non-root UID:GID: {role}")
        _configured_vulnerability_policy(config, role)
        if role == "formal-runner":
            embedded_paths = raw_settings.get("embedded_source_paths")
            if not isinstance(embedded_paths, list) or not embedded_paths:
                raise ReleaseError(
                    "formal-runner embedded_source_paths must be a non-empty array"
                )
            normalized_paths = [
                _safe_relative(str(path), label="formal embedded source path")
                for path in embedded_paths
            ]
            if len(normalized_paths) != len(set(normalized_paths)):
                raise ReleaseError("formal-runner embedded source paths contain duplicates")
        normalized[role] = {"platform": platform, "user": user}
    return normalized


def _parse_role_paths(values: Any, *, label: str) -> dict[str, Path]:
    if not isinstance(values, list):
        raise ReleaseError(f"{label} arguments must be repeated ROLE=PATH values")
    result: dict[str, Path] = {}
    for raw in values:
        role, separator, path_text = str(raw).partition("=")
        if separator != "=" or ROLE_RE.fullmatch(role) is None or not path_text:
            raise ReleaseError(f"invalid {label} argument: {raw!r}")
        if role in result:
            raise ReleaseError(f"duplicate {label} role: {role}")
        result[role] = Path(path_text)
    return result


def _container_inputs_from_args(
    args: argparse.Namespace,
    roles: Mapping[str, Any],
) -> dict[str, tuple[Path, Path, Path, Path]]:
    images = _parse_role_paths(args.image, label="image")
    metadata = _parse_role_paths(args.image_metadata, label="image metadata")
    sboms = _parse_role_paths(args.sbom, label="SBOM")
    vulnerability_reports = _parse_role_paths(
        args.vulnerability_report, label="vulnerability report"
    )
    expected = set(roles)
    for label, mapping in (
        ("image", images),
        ("image metadata", metadata),
        ("SBOM", sboms),
        ("vulnerability report", vulnerability_reports),
    ):
        if set(mapping) != expected:
            raise ReleaseError(
                f"{label} roles do not match config.containers.roles; "
                f"expected={sorted(expected)}, got={sorted(mapping)}"
            )
    return {
        role: (
            images[role],
            metadata[role],
            sboms[role],
            vulnerability_reports[role],
        )
        for role in sorted(expected)
    }


def build_release(args: argparse.Namespace, config: Mapping[str, Any]) -> None:
    repo = args.repo.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ReleaseError(f"refusing to overwrite existing release path: {output}")
    identity, code_manifest, receipts, protocol = _preflight(repo, args.tag, config)
    code_hash = canonical_sha256(code_manifest)
    common_bindings = {
        "git_commit": identity["commit"],
        "git_tree": identity["tree"],
        "code_manifest_sha256": code_hash,
        "protocol_sha256": protocol["canonical_sha256"],
    }
    prover_config = config.get("prover")
    if not isinstance(prover_config, dict):
        raise ReleaseError("config.prover must be an object")
    prover_dir = repo / str(prover_config.get("directory", ""))
    prover_manifest = build_prover_manifest(
        prover_dir,
        prover_config,
        bindings=common_bindings,
        receipt_artifact_sha256=receipts["circuit_artifact_sha256"],
        ptau_root=repo,
    )
    container_roles = _configured_container_roles(config)
    image_inputs = _container_inputs_from_args(args, container_roles)
    images: dict[str, dict[str, Any]] = {}
    for role, (image_tar, metadata_path, sbom_path, vulnerability_path) in image_inputs.items():
        metadata = _load_json_bytes(metadata_path.read_bytes(), label=str(metadata_path))
        verified = verify_image_metadata(
            image_tar,
            metadata,
            role=role,
            bindings=common_bindings,
            platform=container_roles[role]["platform"],
            user=container_roles[role]["user"],
        )
        if role == "formal-runner":
            verified = {
                **verified,
                "embedded_source": verify_formal_runner_embedded_source(
                    image_tar,
                    code_manifest=code_manifest,
                    config=config,
                    bindings=common_bindings,
                ),
            }
        verify_sbom(
            sbom_path,
            role=role,
            image_metadata=verified,
            bindings=common_bindings,
        )
        verify_vulnerability_report(
            vulnerability_path,
            role=role,
            image_metadata=verified,
            bindings=common_bindings,
            config=config,
        )
        images[role] = verified
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="waybill-release-", dir=output.parent) as raw_temp:
        stage = Path(raw_temp) / "release"
        stage.mkdir()
        write_canonical_json(stage / "code-manifest-v2.json", code_manifest)
        (stage / "protocol.json").write_bytes(git_blob(repo, args.tag, protocol["path"]))
        create_source_bundle(repo, args.tag, stage / "source.bundle")
        verify_source_bundle(stage / "source.bundle", args.tag, identity)
        raw_tar = stage / "prover.tar"
        write_deterministic_tar(
            raw_tar, prover_dir, prover_manifest, mtime=int(identity["commit_time_epoch"])
        )
        verify_prover_archive(raw_tar, expected_bindings=common_bindings)
        if shutil.which("zstd") is None:
            raise ReleaseError("zstd is required to build the prover.tar.zst release asset")
        _run(("zstd", "--quiet", "-19", "--threads=1", "--force", str(raw_tar), "-o", str(stage / "prover.tar.zst")))
        raw_tar.unlink()
        tag_assets = config.get("tag_assets")
        if not isinstance(tag_assets, dict):
            raise ReleaseError("config.tag_assets must be an object")
        for destination, source in tag_assets.items():
            safe_destination = _safe_relative(str(destination), label="tag asset destination")
            (stage / safe_destination).parent.mkdir(parents=True, exist_ok=True)
            (stage / safe_destination).write_bytes(git_blob(repo, args.tag, str(source)))
        for role, (image_tar, _, sbom_path, vulnerability_path) in image_inputs.items():
            _copy_regular(image_tar, stage / "containers" / f"{role}-image.tar")
            _copy_regular(sbom_path, stage / "containers" / f"{role}-sbom.spdx.json")
            _copy_regular(
                vulnerability_path,
                stage / "containers" / f"{role}-vulnerabilities.trivy.json",
            )
        container_manifest = {
            "schema": "waybill-container-manifest/v1",
            "bindings": common_bindings,
            "images": images,
        }
        write_canonical_json(stage / "container-manifest.json", container_manifest)
        release_manifest = {
            "schema": "waybill-formal-release-manifest/v2",
            "release_name": config.get("release_name"),
            "identity": identity,
            "bindings": common_bindings,
            "profile": {key: value for key, value in receipts.items() if key != "circuit_artifact_sha256"},
            "config_path": verify_tagged_config(repo, args.tag, config),
            "config_sha256": canonical_sha256(config),
            "assets": _release_assets(stage),
        }
        write_canonical_json(stage / "release-manifest.json", release_manifest)
        write_sha256sums(stage)
        verify_release(stage, config=config)
        stage.rename(output)


def verify_release(release_dir: Path, *, config: Mapping[str, Any] | None = None) -> None:
    manifest = verify_release_inventory(release_dir)
    identity = manifest.get("identity")
    bindings = manifest.get("bindings")
    if not isinstance(identity, dict) or not isinstance(bindings, dict):
        raise ReleaseError("release manifest identity/bindings are invalid")
    code_path = release_dir / "code-manifest-v2.json"
    code = _load_json_bytes(code_path.read_bytes(), label=str(code_path))
    if code.get("schema") != "waybill-code-manifest/v2":
        raise ReleaseError("unsupported code manifest schema")
    if canonical_sha256(code) != bindings.get("code_manifest_sha256"):
        raise ReleaseError("code manifest binding mismatch")
    tag = str(identity.get("tag", ""))
    config_path = _safe_relative(
        str(manifest.get("config_path", "")),
        label="release config path",
    )
    with _source_bundle_repository(release_dir / "source.bundle", tag, identity) as source_repo:
        tagged_config = _load_json_bytes(
            git_blob(source_repo, tag, config_path),
            label=config_path,
        )
        if tagged_config.get("schema") != "waybill-release-finalizer-config/v2":
            raise ReleaseError("unsupported tagged release config schema")
        if tagged_config.get("config_path") != config_path:
            raise ReleaseError("release config path does not match the tagged config")
        if config is not None and canonical_sha256(config) != canonical_sha256(tagged_config):
            raise ReleaseError("caller config does not match the tagged release config")
        effective_config = tagged_config
        if manifest.get("config_sha256") != canonical_sha256(effective_config):
            raise ReleaseError("release config binding mismatch")
        if manifest.get("release_name") != effective_config.get("release_name"):
            raise ReleaseError("release name does not match the tagged config")
        _verify_code_manifest_in_repo(
            source_repo,
            tag,
            identity,
            code,
            effective_config,
        )
        receipt_bindings = verify_profile_and_receipts(
            source_repo,
            tag,
            effective_config,
        )
        expected_profile = {
            key: value
            for key, value in receipt_bindings.items()
            if key != "circuit_artifact_sha256"
        }
        if manifest.get("profile") != expected_profile:
            raise ReleaseError("release profile/receipt summary does not match the source bundle")
        tagged_protocol = protocol_binding(source_repo, tag, effective_config)
        protocol_path = release_dir / "protocol.json"
        protocol_blob = protocol_path.read_bytes()
        if protocol_blob != git_blob(source_repo, tag, tagged_protocol["path"]):
            raise ReleaseError("protocol artifact does not match the tagged source blob")
        protocol = _load_json_bytes(protocol_blob, label=str(protocol_path))
        if canonical_sha256(protocol) != bindings.get("protocol_sha256"):
            raise ReleaseError("protocol artifact binding mismatch")
        tag_assets = effective_config.get("tag_assets")
        if not isinstance(tag_assets, dict):
            raise ReleaseError("config.tag_assets must be an object")
        for destination, source in tag_assets.items():
            safe_destination = _safe_relative(str(destination), label="tag asset destination")
            asset = release_dir / safe_destination
            if not asset.is_file() or asset.is_symlink():
                raise ReleaseError(f"release is missing tagged asset: {safe_destination}")
            if asset.read_bytes() != git_blob(source_repo, tag, str(source)):
                raise ReleaseError(f"release tagged asset differs from source bundle: {safe_destination}")

    prover_manifest = verify_prover_archive(
        release_dir / "prover.tar.zst",
        expected_bindings=bindings,
    )
    prover_config = effective_config.get("prover")
    prover_files = prover_config.get("files") if isinstance(prover_config, dict) else None
    if not isinstance(prover_files, dict):
        raise ReleaseError("config.prover.files must be an object")
    prover_records = prover_manifest.get("files")
    if not isinstance(prover_records, list):
        raise ReleaseError("prover manifest files must be an array")
    by_role = {
        str(record.get("role")): record
        for record in prover_records
        if isinstance(record, dict)
    }
    if set(by_role) != set(prover_files) or len(by_role) != len(prover_records):
        raise ReleaseError("prover manifest roles do not match the tagged config")
    receipt_hashes = receipt_bindings["circuit_artifact_sha256"]
    for role, raw_path in prover_files.items():
        record = by_role[role]
        if record.get("path") != _safe_relative(str(raw_path), label=f"prover file {role}"):
            raise ReleaseError(f"prover manifest path mismatch: {role}")
        if record.get("sha256") != receipt_hashes.get(role):
            raise ReleaseError(f"prover manifest is not bound to the circuit receipt: {role}")
    container_path = release_dir / "container-manifest.json"
    containers = _load_json_bytes(container_path.read_bytes(), label=str(container_path))
    if containers.get("schema") != "waybill-container-manifest/v1" or containers.get("bindings") != bindings:
        raise ReleaseError("container manifest binding mismatch")
    images = containers.get("images")
    container_roles = _configured_container_roles(effective_config)
    if not isinstance(images, dict) or set(images) != set(container_roles):
        raise ReleaseError("container manifest roles do not match the tagged config")
    for role, metadata in images.items():
        if not isinstance(metadata, dict):
            raise ReleaseError(f"invalid container metadata: {role}")
        image_tar = release_dir / "containers" / f"{role}-image.tar"
        verified = verify_image_metadata(
            image_tar,
            metadata,
            role=role,
            bindings=bindings,
            platform=container_roles[role]["platform"],
            user=container_roles[role]["user"],
        )
        if role == "formal-runner":
            embedded_source = verify_formal_runner_embedded_source(
                image_tar,
                code_manifest=code,
                config=effective_config,
                bindings=bindings,
            )
            if metadata.get("embedded_source") != embedded_source:
                raise ReleaseError("formal-runner embedded source receipt mismatch")
        verify_sbom(
            release_dir / "containers" / f"{role}-sbom.spdx.json",
            role=role,
            image_metadata=verified,
            bindings=bindings,
        )
        verify_vulnerability_report(
            release_dir / "containers" / f"{role}-vulnerabilities.trivy.json",
            role=role,
            image_metadata=verified,
            bindings=bindings,
            config=effective_config,
        )


def _path(value: str) -> Path:
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight", help="validate tagged release inputs")
    preflight.add_argument("--repo", type=_path, default=Path.cwd())
    preflight.add_argument("--tag", required=True)
    preflight.add_argument("--config", type=_path, required=True)
    preflight.add_argument("--output-manifest", type=_path)

    image_metadata = subparsers.add_parser(
        "image-metadata",
        help="derive and verify one image metadata document from a saved archive",
    )
    image_metadata.add_argument("--image", type=_path, required=True)
    image_metadata.add_argument("--role", required=True)
    image_metadata.add_argument("--image-ref", required=True)
    image_metadata.add_argument("--config", type=_path, required=True)
    image_metadata.add_argument("--preflight", type=_path, required=True)
    image_metadata.add_argument("--output", type=_path, required=True)

    bind_sbom = subparsers.add_parser(
        "bind-sbom",
        help="bind a scanner-produced SPDX JSON SBOM to one verified image",
    )
    bind_sbom.add_argument("--input", type=_path, required=True)
    bind_sbom.add_argument("--metadata", type=_path, required=True)
    bind_sbom.add_argument("--role", required=True)
    bind_sbom.add_argument("--preflight", type=_path, required=True)
    bind_sbom.add_argument("--output", type=_path, required=True)

    bind_vulnerabilities = subparsers.add_parser(
        "bind-vulnerability-report",
        help="bind and policy-check a Trivy JSON report for one verified image",
    )
    bind_vulnerabilities.add_argument("--input", type=_path, required=True)
    bind_vulnerabilities.add_argument("--metadata", type=_path, required=True)
    bind_vulnerabilities.add_argument("--role", required=True)
    bind_vulnerabilities.add_argument("--config", type=_path, required=True)
    bind_vulnerabilities.add_argument("--preflight", type=_path, required=True)
    bind_vulnerabilities.add_argument("--output", type=_path, required=True)

    build = subparsers.add_parser("build", help="build and self-verify a release directory")
    build.add_argument("--repo", type=_path, default=Path.cwd())
    build.add_argument("--tag", required=True)
    build.add_argument("--config", type=_path, required=True)
    build.add_argument("--output", type=_path, required=True)
    build.add_argument(
        "--image",
        action="append",
        required=True,
        metavar="ROLE=PATH",
        help="repeat once for every config.containers.roles image tar",
    )
    build.add_argument(
        "--image-metadata",
        action="append",
        required=True,
        metavar="ROLE=PATH",
        help="repeat once for every config.containers.roles metadata JSON",
    )
    build.add_argument(
        "--sbom",
        action="append",
        required=True,
        metavar="ROLE=PATH",
        help="repeat once for every config.containers.roles SPDX JSON",
    )
    build.add_argument(
        "--vulnerability-report",
        action="append",
        required=True,
        metavar="ROLE=PATH",
        help="repeat once for every config.containers.roles bound Trivy JSON",
    )

    verify = subparsers.add_parser("verify", help="verify a completed release directory")
    verify.add_argument("--release", type=_path, required=True)
    verify.add_argument("--config", type=_path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            config = load_config(args.config)
            identity, code, receipts, protocol = _preflight(args.repo, args.tag, config)
            result = {
                "schema": "waybill-release-preflight/v2",
                "identity": identity,
                "code_manifest_sha256": canonical_sha256(code),
                "protocol": protocol,
                "receipts": receipts,
            }
            if args.output_manifest:
                write_canonical_json(args.output_manifest, result)
            print(canonical_json(result))
        elif args.command == "image-metadata":
            metadata = create_image_metadata(
                image_tar=args.image,
                role=str(args.role),
                image_ref=str(args.image_ref),
                config=load_config(args.config),
                preflight=_load_json_bytes(
                    args.preflight.read_bytes(), label=str(args.preflight)
                ),
            )
            write_new_canonical_json(args.output, metadata)
            print(canonical_json(metadata))
        elif args.command == "bind-sbom":
            sbom = bind_scanner_sbom(
                raw_sbom_path=args.input,
                metadata_path=args.metadata,
                role=str(args.role),
                preflight=_load_json_bytes(
                    args.preflight.read_bytes(), label=str(args.preflight)
                ),
            )
            write_new_canonical_json(args.output, sbom)
            print(
                canonical_json(
                    {
                        "schema": "waybill-bound-sbom-result/v1",
                        "output": str(args.output),
                        "packages": len(sbom["packages"]),
                        "role": str(args.role),
                        "sha256": sha256_file(args.output),
                    }
                )
            )
        elif args.command == "bind-vulnerability-report":
            report = bind_scanner_vulnerability_report(
                raw_report_path=args.input,
                metadata_path=args.metadata,
                role=str(args.role),
                preflight=_load_json_bytes(
                    args.preflight.read_bytes(), label=str(args.preflight)
                ),
                config=load_config(args.config),
            )
            write_new_canonical_json(args.output, report)
            print(
                canonical_json(
                    {
                        "schema": "waybill-bound-vulnerability-report-result/v1",
                        "output": str(args.output),
                        "role": str(args.role),
                        "sha256": sha256_file(args.output),
                        "summary": report["waybillBinding"]["summary"],
                    }
                )
            )
        elif args.command == "build":
            build_release(args, load_config(args.config))
            print(f"verified release created at {args.output}")
        elif args.command == "verify":
            verify_config = load_config(args.config) if args.config else None
            verify_release(args.release, config=verify_config)
            print(f"verified release: {args.release}")
        else:
            raise ReleaseError(f"unsupported release command: {args.command}")
    except (ReleaseError, OSError, ValueError, KeyError) as exc:
        parser = build_parser()
        parser.exit(1, f"release finalizer failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
