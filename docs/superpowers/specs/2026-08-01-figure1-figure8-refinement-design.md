# Figure 1 and Figure 8 Refinement Design

## Scope

This revision changes only the Figure 1 layout and the Figure 8 explanatory
text. It does not alter the experimental data, security claims, method names,
or results.

## Figure 1

The supplied `overview_refined.png` remains the visual and semantic reference.
The revised figure will preserve its white background, blue and green palette,
rounded panels, icons, equations, labels, and three-stage narrative.

The composition will use a less panoramic canvas. The SHTPC semantic-closure
panel will receive the largest area. Its five interface boxes will be arranged
in two rows. Steps 1, 2, and 3 will appear in the first row. Steps 4 and 5 will
appear in the second row. Directional connectors will preserve the sequence
from I1 through I5. The role-separable validation panel and end-to-end result
panel will be compact supporting panels. No technical content will be removed.

The target aspect ratio is approximately 1.45 to 1.60. Text must remain legible
at double-column width. The image must not contain stretched boxes, corrupted
equations, altered method names, added decorations, or a watermark.

## Figure 8 explanation

The subsection will explain two distinct evaluation questions. The first is
whether one registered DP release configuration gives comparable clean
heatmap utility across datasets with different cohort sizes. The second is
whether SHTPC retains its integrity advantage after the same sampled noise is
applied to each matched method.

The revised caption will define the metric in each panel, explain that a
positive error gap favors SHTPC, identify the paired-noise design, and state
that GeoLife is interpreted separately because it contains only 16 actors.

The revised discussion will explain the low-budget F1 collapse, the different
high-budget outcomes, the positive gap in all 24 matched conditions, and the
nonmonotonicity caused by thresholding and top-50 selection. It will conclude
that Figure 8 supports integrity preservation under matched noise. It will not
claim generally useful DP release quality or comparable utility across cohort
sizes.

## Verification

- Inspect the generated Figure 1 at full resolution for text and equation
  accuracy.
- Compile the paper with Biber and pdfLaTeX.
- Render the Figure 1 and Figure 8 pages.
- Confirm that the new Figure 1 is visibly less panoramic and that all five
  semantic-closure boxes are readable.
- Confirm that the Figure 8 caption and discussion match the plotted data.
- Confirm that compilation has no errors, undefined references, or overfull
  boxes.
