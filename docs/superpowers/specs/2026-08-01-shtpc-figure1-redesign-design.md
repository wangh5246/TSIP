# SHTPC Figure 1 Redesign Specification

## Objective

Redesign Figure 1 as a submission-grade security-systems schematic that explains one claim. Separately valid trajectory admission and aggregation payload checks do not guarantee that both refer to the same hidden primary cell. SHTPC closes this gap by binding accepted state, hidden coordinates, the coordinate-derived primary, delivered share packages, authenticated report sets, and reconstruction.

The redesign must eliminate the empty lower-left area and the generic AI-infographic appearance without copying artwork from published papers.

## Evidence and visual precedents

The figure uses original graphics while adopting established structural conventions from the following papers.

- Prio, NSDI 2017. Use a compact causal pipeline from submission through validation and accumulation to release.
- Prochlo, SOSP 2017. Separate responsibilities visually and mark trust or role boundaries without decorative containers.
- EIFFeL, CCS 2022. Represent input integrity as a verification gate before aggregation.
- Whisper, IEEE Symposium on Security and Privacy 2024. Show one client submission split toward two non-colluding servers and restrict server-to-server exchange to the required check.
- ACORN, USENIX Security 2023. Use numbered protocol gates and reserve red for the integrity failure or additional validation step.
- Mastic, Proceedings on Privacy Enhancing Technologies 2025. Represent two-aggregator validation and reconstruction as protocol actions rather than illustrative metaphors.

No published icon, diagram fragment, logo, or distinctive artwork will be copied. Only layout grammar and generic protocol notation will be reused.

## Figure contract

### Core conclusion

One jointly checked semantic relation is necessary to ensure that the reconstructed pre-noise heatmap contains the contribution derived from the accepted hidden coordinate.

### Archetype

Schematic-led composite with one central role-swimlane hero panel and two narrower explanatory panels.

### Output

- Landscape aspect ratio close to 16:9.
- Intended placement at approximately `0.96\textwidth` in an IEEE two-column manuscript.
- High-resolution PNG draft for immediate manuscript use.
- All labels must remain readable after full-width scaling.
- White background with no texture, gradient, shadow, or watermark.

## Layout

The canvas is divided into three vertical regions with approximate widths of 23 percent, 54 percent, and 23 percent.

### Region 1. Separated validation

The upper portion contains two compact validation lanes.

1. Trajectory admission derives primary cell `p` from a valid hidden trajectory and is checked by the Shuffler.
2. Aggregation validation accepts a valid one-hot payload routed to primary cell `q` and is checked by the Aggregators.

The lower portion explains the failure causally rather than displaying an oversized warning poster.

- Two accepted outputs, `p` and `q`, are shown side by side.
- A red inequality symbol marks the missing cross-role relation.
- Two small grid-cell glyphs show mass removed from the truthful cell and placed in the routed cell.
- A short sentence states that both local checks pass while the reconstructed heatmap moves mass from `p` to `q`.

This content fills the formerly empty lower-left area with scientific meaning.

### Region 2. SHTPC semantic closure

The central hero panel uses four horizontal role lanes.

- Client
- Shuffler
- Aggregators A and R
- Decoder

Five semantic gates are arranged across these lanes.

1. State continuity
2. Hidden trajectory validity
3. Coordinate-to-primary derivation
4. Delivered A and R package binding
5. Equal authenticated report sets and reconstruction

The gates are not displayed as five equally sized independent cards. They are placed where the responsible role acts. Thin arrows indicate only actual message flow, state advancement, or equality checking. No arrow is used merely to imply a total chronological order.

The client-to-aggregator path splits into blue package A and green package R. Aggregator-to-aggregator communication is shown only at the report-set comparison. The Decoder reconstructs only when the authenticated report identifiers agree.

A restrained blue band below the lanes states that one report context binds state, coordinate, primary, delivered packages, and reconstruction. A secondary sentence states that no single role receives all private openings.

### Region 3. End-to-end guarantee

The upper block states coordinate-to-aggregate consistency and shows the equality between the reconstructed pre-noise heatmap and coordinate-derived contributions.

A compact heatmap glyph leads to the unchanged downstream differentially private release.

The lower block reports scope with equal visual weight.

- Included. Post-enrollment semantic consistency.
- Excluded. Physical presence or truthful genesis.
- Excluded. Trajectory anonymity.
- Excluded. Malicious-Shuffler correctness.
- Excluded. Privacy under Aggregator collusion.

## Visual system

- Ink text and outlines. `#202833`.
- Proof and binding blue. `#1F5FBF`.
- Accepted reconstruction green. `#2E7D32`.
- Failure red. `#C62828`.
- Secondary text gray. `#66717E`.
- Neutral divider gray. `#AEB7C2`.
- Pale backgrounds may use only near-white blue, green, or red tints.

Typography uses a neutral sans-serif family. Headings, role labels, equations, and short explanatory text follow a clear hierarchy. The figure contains no decorative shield, glossy warning icon, 3D package, gradient, cast shadow, pseudo-handwritten font, or ornamental arrow.

## Scientific and review-risk checks

- The left panel must not imply that the Shuffler sees the aggregation payload.
- The central arrows must not imply a strict total order among all five semantic conditions.
- Package A and package R must remain visually distinct and must terminate at their corresponding Aggregators.
- The equal-report-set check must occur before reconstruction.
- Differential privacy must appear downstream of pre-noise consistency and must not be presented as the source of integrity.
- The figure must not claim physical location truthfulness, anonymity, malicious-Shuffler correctness, or collusion privacy.
- No unsupported numerical result will be inserted.
- All equations and labels will be checked against the manuscript before delivery.

## Acceptance criteria

The redesign is accepted when a reviewer can identify the local-validation failure, the cross-role binding introduced by SHTPC, the dual-aggregator delivery path, the reconstruction condition, and the explicit claim boundary without reading the caption. Text must remain readable at manuscript scale, and the lower-left region must carry causal evidence rather than decorative whitespace.
