#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ABSTRACT_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)
STALE_PATTERNS = {
    r"3(?:\{,\}|,)056": "stale constraint count 3,056",
    r"\b14\s+public inputs\b": "stale 14-public-input paper claim",
    r"\b23\s+private inputs\b": "stale 23-private-input paper claim",
    r"eq:r-tsip": "stale internal TSIP label",
}
REQUIRED_MACROS = (
    r"\VFourConstraints",
    r"\VFourPublicInputs",
    r"\VFourPrivateInputs",
)
SCALE_COMPLETE_PATTERNS = (
    r"\b15\s*/\s*15\s+units?\s+"
    r"(?:(?:have|has)\s+been\s+|(?:have|has|are|is|was|were)\s+)?"
    r"(?:passed|completed(?:\s+successfully)?|successful|successfully\s+completed)\b",
    r"(?<!not\s)\ball\s+15\s+dataset[- ]seed\s+units?\s+"
    r"(?:(?:have|has)\s+been\s+|(?:have|has|are|is|was|were)\s+)?"
    r"(?:passed|completed(?:\s+successfully)?|successful|successfully\s+completed)\b",
)

_DATASETS = ("T-Drive", "GeoLife", "Porto", "Rome", "Synthetic")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
_COMMAND_RE = re.compile(r"\\[A-Za-z@]+\*?(?:\s*\[[^]]*\])?")
_COMMENT_RE = re.compile(r"(?<!\\)%[^\r\n]*")


def latex_word_count(text: str) -> int:
    text = _COMMENT_RE.sub(" ", text)
    text = _COMMAND_RE.sub(" ", text)
    text = re.sub(r"[{}$~^_]", " ", text)
    return len(_WORD_RE.findall(text))


def _scale_status(evidence: dict[str, Any]) -> object:
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be a JSON object")
    scale = evidence.get("scale", {})
    if not isinstance(scale, dict):
        raise ValueError("evidence scale must be an object")
    return scale.get("status")


def check_text(text: str, evidence: dict[str, Any]) -> list[str]:
    scale_status = _scale_status(evidence)
    issues: list[str] = []

    match = ABSTRACT_RE.search(text)
    if not match:
        issues.append("abstract environment missing")
    else:
        words = latex_word_count(match.group(1))
        if not 100 <= words <= 200:
            issues.append(f"abstract word count is {words}, expected 100..200")

    for pattern, message in STALE_PATTERNS.items():
        if re.search(pattern, text, re.I):
            issues.append(message)

    for dataset in _DATASETS:
        if dataset not in text:
            issues.append(f"dataset missing from manuscript: {dataset}")

    for macro in REQUIRED_MACROS:
        if not re.search(re.escape(macro) + r"(?![A-Za-z@])", text):
            issues.append(f"artifact macro missing from manuscript: {macro}")

    scale_complete_claimed = any(
        re.search(pattern, text, re.I | re.S) for pattern in SCALE_COMPLETE_PATTERNS
    )
    if scale_status != "verified" and scale_complete_claimed:
        issues.append(
            "manuscript claims 15/15 completion while scale evidence is partial"
        )
    return issues


def abstract_words(text: str) -> int | None:
    match = ABSTRACT_RE.search(text)
    return latex_word_count(match.group(1)) if match else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the heatmap manuscript against its evidence contract."
    )
    parser.add_argument("--tex", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    return parser.parse_args(argv)


def _read_utf8(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {label} file {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        text = _read_utf8(args.tex, "manuscript")
        raw_evidence = _read_utf8(args.evidence, "evidence")
        try:
            evidence = json.loads(raw_evidence)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"cannot parse evidence JSON {args.evidence}: {exc}"
            ) from exc
        if not isinstance(evidence, dict):
            raise ValueError(f"evidence JSON must be an object: {args.evidence}")
        issues = check_text(text, evidence)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {"abstract_words": abstract_words(text), "issues": issues},
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
