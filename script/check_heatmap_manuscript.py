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
    r"(?<!\d)3(?:\{,\}|,)056(?!\d)": "stale constraint count 3,056",
    r"(?<![A-Za-z0-9_])14\s+public\s+inputs(?![A-Za-z0-9_])": (
        "stale 14-public-input paper claim"
    ),
    r"(?<![A-Za-z0-9_])23\s+private\s+inputs(?![A-Za-z0-9_])": (
        "stale 23-private-input paper claim"
    ),
    r"\\(?:label|ref|eqref|autoref|pageref|cref)\*?\s*"
    r"\{\s*eq:r-tsip\s*\}": "stale internal TSIP label",
}
REVIEWER_VISIBLE_INTERNAL_PATTERNS = {
    r"(?<![A-Za-z0-9_])V[1-9]\d*(?![A-Za-z0-9_])": (
        "reviewer-visible internal version label"
    ),
    r"\b(?:old|new|previous|earlier|revised|corrected)\s+version\b": (
        "reviewer-visible version-history wording"
    ),
    r"\b(?:before|after)\s+(?:the\s+)?(?:fix|correction|revision)\b": (
        "reviewer-visible correction-history wording"
    ),
    r"\b(?:legacy|pre[- ]manifest|archive[- ]compatibility)\b": (
        "reviewer-visible implementation-history wording"
    ),
    r"\bhistorical\s+(?:performance|cost|benchmark|receipt|relation|engineering)\b": (
        "reviewer-visible historical-result wording"
    ),
    r"\barchived\s+\d{4}-\d{2}-\d{2}\b": (
        "reviewer-visible dated archive wording"
    ),
    r"\bcurrent[- ]circuit\b|\bcurrent\s+paper\s+(?:circuit|relation)\b": (
        "reviewer-visible internal circuit-version wording"
    ),
    r"\bleft\s+unclaimed\b": "reviewer-visible drafting note",
    r"\bpending\s+repository[- ]license\b": "reviewer-visible release TODO",
    r"\bsimulated\s+reviewer\s+reports\b|\bself[- ]review\s+notes\b": (
        "reviewer-visible internal review-process wording"
    ),
    r"\bbefore\s+submission\b[^.]{0,160}\bauthors?\s+must\b": (
        "reviewer-visible submission TODO"
    ),
}
REQUIRED_MACROS = (
    r"\VFourConstraints",
    r"\VFourPublicInputs",
    r"\VFourPrivateInputs",
)
REQUIRED_VERIFIED_SCALE_MACROS = (
    r"\VFourScaleUnits",
    r"\VFourScaleProofs",
    r"\VFourScaleProofFailures",
    r"\VFourScaleEvaluationRounds",
    r"\VFourScaleRouteA",
    r"\VFourScaleRouteR",
    r"\VFourScaleReconstructions",
    r"\VFourScaleDPReleases",
    r"\VFourScaleTimingUnits",
    r"\VFourScaleTimingExcluded",
    r"\VFourScaleThroughputMean",
    r"\VFourScaleThroughputStd",
    r"\VFourScaleWallHoursMean",
    r"\VFourScaleWallHoursStd",
)
VERIFIED_SCALE_TABLE_RE = re.compile(
    r"\\input\s*\{\s*tables/tab_v4_n1000_scale\s*\}"
)
VERIFIED_SCALE_DISCLOSURES = (
    (
        re.compile(r"\bhost[- ]suspension\b", re.I),
        "verified scale host-suspension disclosure missing",
    ),
    (
        re.compile(r"\bRome(?:\s+seed|\s*/)?\s*101\b", re.I),
        "verified scale excluded pair missing: Rome seed 101",
    ),
    (
        re.compile(r"\bSynthetic(?:\s+seed|\s*/)?\s*101\b", re.I),
        "verified scale excluded pair missing: Synthetic seed 101",
    ),
    (
        re.compile(r"\bexcluded\s+only\s+from\s+timing(?:\s+statistics)?\b", re.I),
        "verified scale timing-only exclusion disclosure missing",
    ),
)
POLISH_DISCLOSURES = (
    (
        re.compile(r"\bApple\s+M4\b", re.I),
        "experiment host disclosure missing: Apple M4",
    ),
    (
        re.compile(r"\b16\s*GB\b", re.I),
        "experiment host-memory disclosure missing: 16 GB",
    ),
    (
        re.compile(
            r"\b(?:10\s+Docker\s+CPUs|Docker[^.]{0,40}\b10\s+CPUs)\b",
            re.I | re.S,
        ),
        "Docker CPU allocation disclosure missing",
    ),
    (
        re.compile(r"\b8\.22\s*GB\b", re.I),
        "Docker memory allocation disclosure missing",
    ),
    (
        re.compile(
            r"\bdo\s+not\s+(?:claim|interpret)[^.]{0,100}"
            r"statistical\s+significance\b",
            re.I | re.S,
        ),
        "small-gain significance boundary missing",
    ),
)
SCALE_COMPLETE_PATTERNS = (
    r"\b15\s*/\s*15\s+(?:dataset[- ]seed\s+)?units?\s+"
    r"(?:(?:have|has)\s+been\s+|(?:have|has|are|is|was|were)\s+)?"
    r"(?:passed|completed(?:\s+successfully)?|successful|successfully\s+completed)\b",
    r"\ball\s+15\s+(?:dataset[- ]seed\s+)?units?\s+"
    r"(?:(?:have|has)\s+been\s+|(?:have|has|are|is|was|were)\s+)?"
    r"(?:passed|completed(?:\s+successfully)?|successful|successfully\s+completed)\b",
)

_DATASETS = ("T-Drive", "GeoLife", "Porto", "Rome", "Synthetic")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
_COMMAND_RE = re.compile(r"\\[A-Za-z@]+\*?(?:\s*\[[^]]*\])?")
_DEFINITION_RE = re.compile(
    r"\\(?P<command>newcommand|renewcommand|providecommand|def)"
    r"(?![A-Za-z@])\*?"
)
_NON_RENDERED_COMMAND_RE = re.compile(
    r"\\(?:"
    r"label|ref|eqref|autoref|pageref|cref|Cref|"
    r"input|include|includegraphics|bibliography|bibliographystyle|"
    r"addbibresource|cite|citep|citet|parencite|textcite|nocite"
    r")\*?"
)
_CONTROL_SEQUENCE_RE = re.compile(r"\\(?:[A-Za-z@]+|.)")
_NON_COMPLETION_RE = re.compile(
    r"\s*[,;:]?\s*(?:but\s+)?(?:only\s+)?"
    r"(?:partial(?:ly)?|incomplete(?:ly)?)\b",
    re.I,
)


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _strip_latex_comments(text: str) -> str:
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] == "%" and not _is_escaped(text, index):
            parts.append(text[start:index])
            newline = text.find("\n", index)
            if newline == -1:
                return "".join(parts)
            parts.append("\n")
            index = newline + 1
            start = index
        else:
            index += 1
    parts.append(text[start:])
    return "".join(parts)


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _group_end(
    text: str, start: int, opening: str, closing: str
) -> int | None:
    if start >= len(text) or text[start] != opening:
        return None
    depth = 0
    for index in range(start, len(text)):
        if _is_escaped(text, index):
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _definition_end(text: str, match: re.Match[str]) -> int:
    command = match.group("command")
    index = _skip_whitespace(text, match.end())

    if command == "def":
        target = _CONTROL_SEQUENCE_RE.match(text, index)
        if not target:
            return match.end()
        index = target.end()
        while index < len(text):
            if text[index] == "{" and not _is_escaped(text, index):
                return _group_end(text, index, "{", "}") or len(text)
            index += 1
        return index

    if index < len(text) and text[index] == "{":
        target_end = _group_end(text, index, "{", "}")
        if target_end is None:
            return len(text)
        index = target_end
    else:
        target = _CONTROL_SEQUENCE_RE.match(text, index)
        if not target:
            return match.end()
        index = target.end()

    index = _skip_whitespace(text, index)
    while index < len(text) and text[index] == "[":
        option_end = _group_end(text, index, "[", "]")
        if option_end is None:
            return len(text)
        index = _skip_whitespace(text, option_end)
    if index < len(text) and text[index] == "{":
        return _group_end(text, index, "{", "}") or len(text)
    return index


def _without_macro_definitions(text: str) -> str:
    spans: list[tuple[int, int]] = []
    covered_until = 0
    for match in _DEFINITION_RE.finditer(text):
        if match.start() < covered_until:
            continue
        covered_until = max(match.end(), _definition_end(text, match))
        spans.append((match.start(), covered_until))
    if not spans:
        return text

    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        parts.append(re.sub(r"[^\r\n]", " ", text[start:end]))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _without_nonrendered_commands(text: str) -> str:
    spans: list[tuple[int, int]] = []
    covered_until = 0
    for match in _NON_RENDERED_COMMAND_RE.finditer(text):
        if match.start() < covered_until:
            continue
        index = _skip_whitespace(text, match.end())
        while index < len(text) and text[index] == "[":
            option_end = _group_end(text, index, "[", "]")
            if option_end is None:
                index = len(text)
                break
            index = _skip_whitespace(text, option_end)
        if index < len(text) and text[index] == "{":
            index = _group_end(text, index, "{", "}") or len(text)
        else:
            index = match.end()
        covered_until = index
        spans.append((match.start(), index))

    if not spans:
        return text

    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        parts.append(re.sub(r"[^\r\n]", " ", text[start:end]))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _contains_lexical_token(text: str, token: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


def _scale_complete_claimed(text: str) -> bool:
    for pattern in SCALE_COMPLETE_PATTERNS:
        for match in re.finditer(pattern, text, re.I | re.S):
            prefix = text[max(0, match.start() - 32) : match.start()]
            if re.search(r"\b(?:not|no)\s*$", prefix, re.I):
                continue
            suffix = text[match.end() : match.end() + 64]
            if _NON_COMPLETION_RE.match(suffix):
                continue
            return True
    return False


def latex_word_count(text: str) -> int:
    text = _strip_latex_comments(text)
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
    contract_text = _strip_latex_comments(text)

    match = ABSTRACT_RE.search(contract_text)
    if not match:
        issues.append("abstract environment missing")
    else:
        words = latex_word_count(match.group(1))
        if not 100 <= words <= 200:
            issues.append(f"abstract word count is {words}, expected 100..200")

    for pattern, message in STALE_PATTERNS.items():
        if re.search(pattern, contract_text, re.I):
            issues.append(message)

    reviewer_visible_text = _without_nonrendered_commands(
        _without_macro_definitions(contract_text)
    )
    for pattern, message in REVIEWER_VISIBLE_INTERNAL_PATTERNS.items():
        if re.search(pattern, reviewer_visible_text, re.I | re.S):
            issues.append(message)

    for dataset in _DATASETS:
        if not _contains_lexical_token(contract_text, dataset):
            issues.append(f"dataset missing from manuscript: {dataset}")

    for pattern, message in POLISH_DISCLOSURES:
        if pattern.search(contract_text) is None:
            issues.append(message)
    if (
        re.search(r"\bNebula[- ]style\b", contract_text, re.I) is None
        or re.search(
            r"\bmechanism[- ]level\b[^.]{0,80}\badapter\b",
            contract_text,
            re.I | re.S,
        )
        is None
    ):
        issues.append("mechanism-level Nebula-style adapter disclosure missing")

    macro_text = _without_macro_definitions(contract_text)
    for macro in REQUIRED_MACROS:
        if not re.search(re.escape(macro) + r"(?![A-Za-z@])", macro_text):
            issues.append(f"artifact macro missing from manuscript: {macro}")

    if scale_status != "verified" and _scale_complete_claimed(contract_text):
        issues.append(
            "manuscript claims 15/15 completion while scale evidence is partial"
        )
    elif scale_status == "verified":
        for macro in REQUIRED_VERIFIED_SCALE_MACROS:
            if not re.search(re.escape(macro) + r"(?![A-Za-z@])", macro_text):
                issues.append(
                    f"verified scale macro missing from manuscript: {macro}"
                )
        if VERIFIED_SCALE_TABLE_RE.search(contract_text) is None:
            issues.append("verified scale table missing from manuscript")
        for pattern, message in VERIFIED_SCALE_DISCLOSURES:
            if pattern.search(contract_text) is None:
                issues.append(message)
    return issues


def abstract_words(text: str) -> int | None:
    match = ABSTRACT_RE.search(_strip_latex_comments(text))
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
