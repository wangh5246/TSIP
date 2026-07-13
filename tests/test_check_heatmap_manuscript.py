import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "script" / "check_heatmap_manuscript.py"
SPEC = importlib.util.spec_from_file_location("check_heatmap_manuscript", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

GOOD = r"""
\title{SHTPC: Stateful Hidden Trajectory-Payload Consistency for Private Heatmap Aggregation}
\begin{abstract}
ABSTRACT_BODY
\end{abstract}
T-Drive GeoLife Porto Rome Synthetic
\VFourConstraints{} constraints, \VFourPublicInputs{} public inputs, and
\VFourPrivateInputs{} private inputs.
\label{eq:r-shtpc}
"""
PARTIAL = {"scale": {"status": "partial"}}
VERIFIED = {"scale": {"status": "verified"}}


def paper(words: int = 150) -> str:
    return GOOD.replace("ABSTRACT_BODY", "word " * words)


def test_valid_150_word_partial_scale_manuscript_passes() -> None:
    assert MODULE.check_text(paper(), PARTIAL) == []


@pytest.mark.parametrize("words", [99, 150, 201])
def test_abstract_word_count_is_exact(words: int) -> None:
    assert MODULE.abstract_words(paper(words)) == words


@pytest.mark.parametrize("words", [99, 201])
def test_abstract_word_boundaries_fail(words: int) -> None:
    issues = MODULE.check_text(paper(words), PARTIAL)

    assert any("abstract word count" in issue for issue in issues)


@pytest.mark.parametrize(
    ("stale", "expected"),
    [
        ("3,056", "stale constraint count 3,056"),
        (r"3{,}056", "stale constraint count 3,056"),
        ("14 public inputs", "stale 14-public-input paper claim"),
        ("23 private inputs", "stale 23-private-input paper claim"),
        (r"\label{eq:r-tsip}", "stale internal TSIP label"),
        (r"\ref{eq:r-tsip}", "stale internal TSIP label"),
        (r"\eqref{eq:r-tsip}", "stale internal TSIP label"),
        (r"\autoref{eq:r-tsip}", "stale internal TSIP label"),
    ],
)
def test_stale_current_paper_facts_fail(stale: str, expected: str) -> None:
    assert expected in MODULE.check_text(paper() + stale, PARTIAL)


@pytest.mark.parametrize(
    "fresh",
    [
        "13,056",
        "3,0560",
        r"13{,}056",
        r"3{,}0560",
        "114 public inputs",
        "x14 public inputs",
        "14 public inputs0",
        "14 public inputsets",
        "123 private inputs",
        "x23 private inputs",
        "23 private inputs0",
        "23 private inputsets",
        "eq:r-tsip",
        r"\label{eq:r-tsip-v2}",
        r"\ref{eq:r-tsip-v2}",
        r"\eqref{eq:r-tsip-v2}",
        r"\autoref{eq:r-tsip-v2}",
    ],
)
def test_stale_patterns_do_not_overmatch(fresh: str) -> None:
    issues = MODULE.check_text(paper() + fresh, PARTIAL)

    assert not any(issue.startswith("stale") for issue in issues)


@pytest.mark.parametrize("dataset", ["Porto", "Rome", "Synthetic"])
def test_missing_required_dataset_fails(dataset: str) -> None:
    issues = MODULE.check_text(paper().replace(dataset, ""), PARTIAL)

    assert any("dataset missing" in issue and dataset in issue for issue in issues)


@pytest.mark.parametrize(
    ("dataset", "lookalike"),
    [
        ("T-Drive", "T-Driver"),
        ("GeoLife", "GeoLifestyle"),
        ("Porto", "Portoland"),
        ("Rome", "Romero"),
        ("Synthetic", "Syntheticity"),
    ],
)
def test_dataset_name_requires_lexical_boundaries(
    dataset: str, lookalike: str
) -> None:
    text = paper().replace(dataset, "") + lookalike
    issues = MODULE.check_text(text, PARTIAL)

    assert f"dataset missing from manuscript: {dataset}" in issues


def test_dataset_names_in_comments_do_not_satisfy_contract() -> None:
    datasets = ("T-Drive", "GeoLife", "Porto", "Rome", "Synthetic")
    text = paper()
    for dataset in datasets:
        text = text.replace(dataset, "")
    text += "\n% T-Drive GeoLife Porto Rome Synthetic\n"

    issues = MODULE.check_text(text, PARTIAL)

    for dataset in datasets:
        assert f"dataset missing from manuscript: {dataset}" in issues


@pytest.mark.parametrize(
    "macro",
    [r"\VFourConstraints", r"\VFourPublicInputs", r"\VFourPrivateInputs"],
)
def test_missing_generated_artifact_macro_fails(macro: str) -> None:
    issues = MODULE.check_text(paper().replace(f"{macro}{{}}", ""), PARTIAL)

    assert any("artifact macro missing" in issue and macro in issue for issue in issues)


def without_artifact_macro_uses() -> str:
    text = paper()
    for macro in MODULE.REQUIRED_MACROS:
        text = text.replace(f"{macro}{{}}", "")
    return text


def test_artifact_macros_in_comments_do_not_satisfy_contract() -> None:
    definitions = " ".join(f"{macro}{{}}" for macro in MODULE.REQUIRED_MACROS)
    issues = MODULE.check_text(
        without_artifact_macro_uses() + f"\n% {definitions}\n", PARTIAL
    )

    for macro in MODULE.REQUIRED_MACROS:
        assert f"artifact macro missing from manuscript: {macro}" in issues


@pytest.mark.parametrize(
    "definitions",
    [
        "\n".join(
            rf"\newcommand{{{macro}}}{{value}}"
            for macro in MODULE.REQUIRED_MACROS
        ),
        "\n".join(
            rf"\renewcommand{{{macro}}}{{value}}"
            for macro in MODULE.REQUIRED_MACROS
        ),
        "\n".join(
            rf"\providecommand{{{macro}}}{{value}}"
            for macro in MODULE.REQUIRED_MACROS
        ),
        "\n".join(rf"\def{macro}{{value}}" for macro in MODULE.REQUIRED_MACROS),
        r"""
\newcommand{\EvidenceSummary}{
  \VFourConstraints{} \VFourPublicInputs{} \VFourPrivateInputs{}
}
""",
    ],
)
def test_artifact_macro_definitions_do_not_count_as_uses(definitions: str) -> None:
    issues = MODULE.check_text(
        without_artifact_macro_uses() + definitions, PARTIAL
    )

    for macro in MODULE.REQUIRED_MACROS:
        assert f"artifact macro missing from manuscript: {macro}" in issues


@pytest.mark.parametrize(
    "claim",
    [
        "15/15 units passed.",
        "15/15 dataset-seed units completed successfully.",
        "15/15 units successful.",
        "All 15 units passed.",
        "All 15 dataset-seed units completed successfully.",
        "All 15 dataset-seed units successful.",
    ],
)
def test_complete_scale_claim_fails_while_summary_is_partial(claim: str) -> None:
    issues = MODULE.check_text(paper() + claim, PARTIAL)

    assert (
        "manuscript claims 15/15 completion while scale evidence is partial"
        in issues
    )


@pytest.mark.parametrize(
    "claim",
    [
        "15/15 units remain incomplete.",
        "15/15 dataset-seed units remain incomplete.",
        "15/15 units are only partially completed.",
        "15/15 dataset-seed units are partially completed.",
        "Not all 15 units passed.",
        "Not all 15 dataset-seed units completed successfully.",
        "All 15 units are not completed.",
        "All 15 dataset-seed units remain partially completed.",
        "15/15 units completed only partially.",
        "All 15 units passed only partially.",
        "15/15 units passing checks.",
        "All 15 units completion remains partial.",
    ],
)
def test_incomplete_scale_language_does_not_claim_completion(claim: str) -> None:
    assert MODULE.check_text(paper() + claim, PARTIAL) == []


def test_contract_claims_in_comments_are_ignored() -> None:
    comment = (
        r"% 3,056; 14 public inputs; 23 private inputs; "
        r"\ref{eq:r-tsip}; 15/15 units passed."
    )

    assert MODULE.check_text(paper() + "\n" + comment + "\n", PARTIAL) == []


def test_verified_scale_allows_completion_claim() -> None:
    assert MODULE.check_text(paper() + "15/15 units passed.", VERIFIED) == []


def test_missing_abstract_reports_issue() -> None:
    text = paper().replace(r"\begin{abstract}", "").replace(
        r"\end{abstract}", ""
    )

    assert MODULE.abstract_words(text) is None
    assert "abstract environment missing" in MODULE.check_text(text, PARTIAL)


@pytest.mark.parametrize("evidence", [[], {"scale": []}])
def test_malformed_evidence_fails_clearly(evidence: object) -> None:
    with pytest.raises(ValueError, match="evidence.*object"):
        MODULE.check_text(paper(), evidence)


def test_cli_rejects_non_object_evidence(tmp_path: Path) -> None:
    tex = tmp_path / "paper.tex"
    evidence = tmp_path / "evidence.json"
    tex.write_text(paper(), encoding="utf-8")
    evidence.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tex", str(tex), "--evidence", str(evidence)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert "evidence JSON must be an object" in result.stderr
    assert result.stdout == ""
