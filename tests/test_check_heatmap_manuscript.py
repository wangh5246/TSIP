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
The experiments ran on an Apple M4 host with 16 GB memory. The scale preflight
recorded 10 Docker CPUs and 8.22 GB of Docker memory. We compare a
mechanism-level Nebula-style adapter. We do not claim statistical significance
for the small Porto and Synthetic differences.
The payload harness uses exactly 12 deterministic negative attempts. Two attempts
target proof context. Five target witnesses. Five target routes.
RQ3 uses StandardScaler and then an MLP with 32 and 16 hidden units. The
user-disjoint split uses 700/300 users, 1,400 training pairs, and 600 test pairs.
Session-linking AUC is 0.7434, 0.7491, 0.7268, and 0.7316.
The generic external ESA adapter uses p=1-\exp(-\varepsilon) over
D=10{,}000. It filters raw counts below 3 and uses q=(1-p)/D for debiasing.
\label{eq:r-shtpc}
"""
PARTIAL = {"scale": {"status": "partial"}}
VERIFIED = {"scale": {"status": "verified"}}
VERIFIED_SCALE_MACROS = (
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
VERIFIED_SCALE_CONTRACT = r"""
\input{tables/tab_v4_n1000_scale}
The \VFourScaleUnits{} dataset-seed units produced \VFourScaleProofs{}
verified proofs and \VFourScaleProofFailures{} proof failures. Across
\VFourScaleEvaluationRounds{} evaluation rounds, routes A and R each received
\VFourScaleRouteA{} and \VFourScaleRouteR{} reports, respectively;
\VFourScaleReconstructions{} reconstructions and \VFourScaleDPReleases{} DP
releases passed. Timing uses
\VFourScaleTimingUnits{} units and excludes \VFourScaleTimingExcluded{} units.
The rate is \VFourScaleThroughputMean{} plus or minus
\VFourScaleThroughputStd{} proofs per second, and wall time is
\VFourScaleWallHoursMean{} plus or minus \VFourScaleWallHoursStd{} hours.
Rome seed 101 and Synthetic seed 101 experienced host suspension and were
excluded only from timing statistics while their functional receipts remained
in the proof totals.
"""


def paper(words: int = 150) -> str:
    return GOOD.replace("ABSTRACT_BODY", "word " * words)


def verified_paper(words: int = 150) -> str:
    return paper(words) + VERIFIED_SCALE_CONTRACT


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


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("We report the V4 method.", "reviewer-visible internal version label"),
        ("The old version used fewer checks.", "reviewer-visible version-history wording"),
        ("After the correction, all runs pass.", "reviewer-visible correction-history wording"),
        ("A legacy benchmark is retained.", "reviewer-visible implementation-history wording"),
        ("The pre-manifest run is included.", "reviewer-visible implementation-history wording"),
        ("Historical performance was 3 ms.", "reviewer-visible historical-result wording"),
        ("The archived 2026-05-04 run is shown.", "reviewer-visible dated archive wording"),
        ("The current-circuit result passes.", "reviewer-visible internal circuit-version wording"),
        ("Frame size is left unclaimed.", "reviewer-visible drafting note"),
        ("Release depends on pending repository-license selection.", "reviewer-visible release TODO"),
        ("Simulated reviewer reports are retained.", "reviewer-visible internal review-process wording"),
        ("Before submission, the authors must confirm ethics approval.", "reviewer-visible submission TODO"),
    ],
)
def test_reviewer_visible_internal_process_wording_fails(
    wording: str, expected: str
) -> None:
    assert expected in MODULE.check_text(paper() + wording, PARTIAL)


@pytest.mark.parametrize(
    "source_only",
    [
        "% IEEEtran V1.6 template comment\n",
        r"\newcommand{\VFourConstraints}{3547}",
        r"\input{tables/tab_v4_n1000_scale}",
        r"\label{tab:v4-fixed-utility}",
        r"\ref{tab:v4-fixed-utility}",
        r"\includegraphics{figures/v4_fixed_utility_heatmap.pdf}",
        r"\cite{ProtocolV2Evaluation}",
    ],
)
def test_source_only_version_identifiers_do_not_trigger_review_gate(
    source_only: str,
) -> None:
    issues = MODULE.check_text(paper() + "\n" + source_only, PARTIAL)

    assert not any(issue.startswith("reviewer-visible") for issue in issues)


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
    ("missing", "expected"),
    [
        ("Apple M4", "experiment host disclosure missing: Apple M4"),
        ("16 GB", "experiment host-memory disclosure missing: 16 GB"),
        ("10 Docker CPUs", "Docker CPU allocation disclosure missing"),
        ("8.22 GB", "Docker memory allocation disclosure missing"),
        ("Nebula-style", "mechanism-level Nebula-style adapter disclosure missing"),
        ("mechanism-level", "mechanism-level Nebula-style adapter disclosure missing"),
        ("do not claim statistical significance", "small-gain significance boundary missing"),
        ("exactly 12 deterministic negative attempts", "RQ1 payload-mutation attempt count missing"),
        ("Two attempts", "RQ1 payload-mutation category breakdown missing"),
        ("StandardScaler", "RQ3 classifier architecture disclosure missing"),
        ("user-disjoint", "RQ3 user-disjoint train/test split disclosure missing"),
        ("0.7434", "RQ3 four-dataset session-linking AUC disclosure missing"),
        ("generic external ESA", "external ESA sampling rule disclosure missing"),
        ("filters raw counts below 3", "external ESA threshold and debiasing disclosure missing"),
    ],
)
def test_polished_manuscript_requires_setup_and_comparison_disclosures(
    missing: str, expected: str
) -> None:
    issues = MODULE.check_text(paper().replace(missing, ""), PARTIAL)

    assert expected in issues


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
    assert MODULE.check_text(verified_paper() + "15/15 units passed.", VERIFIED) == []


@pytest.mark.parametrize("macro", VERIFIED_SCALE_MACROS)
def test_verified_scale_requires_generated_scale_macro_use(macro: str) -> None:
    issues = MODULE.check_text(verified_paper().replace(f"{macro}{{}}", ""), VERIFIED)

    assert f"verified scale macro missing from manuscript: {macro}" in issues


def test_verified_scale_requires_generated_scale_table() -> None:
    text = verified_paper().replace(r"\input{tables/tab_v4_n1000_scale}", "")

    assert "verified scale table missing from manuscript" in MODULE.check_text(
        text, VERIFIED
    )


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("host suspension", "verified scale host-suspension disclosure missing"),
        ("Rome seed 101", "verified scale excluded pair missing: Rome seed 101"),
        (
            "Synthetic seed 101",
            "verified scale excluded pair missing: Synthetic seed 101",
        ),
        (
            "excluded only from timing statistics",
            "verified scale timing-only exclusion disclosure missing",
        ),
    ],
)
def test_verified_scale_requires_timing_exclusion_disclosure(
    missing: str, expected: str
) -> None:
    issues = MODULE.check_text(verified_paper().replace(missing, ""), VERIFIED)

    assert expected in issues


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
