# Figure 1 Reference-Layout Restoration Design

## Decision

Restore the previously approved three-column Figure 1 composition shown in the
provided reference. Do not present further layout alternatives. Preserve its
open central protocol area and serif-led paper aesthetic, while correcting all
known overflow and clipping defects.

## Figure contract

- Core conclusion: separately valid admission and aggregation can refer to
  different primary cells, while SHTPC binds the accepted state, hidden
  trajectory, derived primary, delivered packages, and authenticated report
  sets to obtain coordinate-to-aggregate consistency.
- Archetype: schematic-led composite.
- Target: IEEE double-column figure, 183 x 76 mm.
- Backend: Python/Matplotlib only.
- Outputs: editable PDF/SVG, 600-dpi TIFF, and 300-dpi PNG preview.

## Layout

### Left column: separated validation

Use a single narrative column rather than three equal cards. Present trajectory
admission at the top, aggregation input in the middle, and the missing
cross-role relation at the bottom. Thin horizontal rules separate the three
ideas. The `accepted p` and `accepted q` pills flank a red `p != q` relation,
followed by one short consequence statement.

### Centre column: semantic closure

Make the published two-Aggregator VDAF skeleton the hero visual. Place the
Shard/Prep structure in the upper-left and the Agg/Unshard structure beneath
it. Place I1--I4 as a vertically aligned list on the right, with I4's
reconstruction equation in a bounded green callout. Below the hero region,
place one blue semantic-binding bar, then the I5 equal-set statement and the
privacy-opening boundary statement. I1--I5 are obligations of one relation,
not a directional execution sequence.

### Right column: guarantee

Use one green guarantee box fully contained in the column, followed by a short
downward arrow, the unchanged DP release with a clean heatmap crop, and a dashed
Scope box. Scope items use concise parallel wording and wrap within the column.

## Source-component policy

Continue to use only the verified published VDAF, PRIVIC, and PLASMA crops
recorded in the provenance file. Manuscript-native dividers, pills, numbers,
callout boxes, and relational arrows are allowed as explanatory annotations.
Do not introduce an AI-generated protocol component or relabel source-paper
participants as SHTPC roles.

## Overflow prevention and QA

- Assign every critical title, equation, paragraph, and scope item a permitted
  display-coordinate region.
- Make export fail when a checked text bounding box escapes its region.
- Keep all box strokes inside the three panel boundaries.
- Inspect both the standalone 183 x 76 mm export and page 7 of the compiled
  manuscript.
- Run the Nature Figure strict preflight and require zero failures and zero
  unresolved warnings.

## Scope

Only Figure 1, its generator, preview/export bundle, provenance/QA record, and
the compiled manuscript are changed. The paper's claims and source citations
remain unchanged.
