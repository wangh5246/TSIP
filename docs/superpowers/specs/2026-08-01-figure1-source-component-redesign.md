# Figure 1 source-component redesign

## Objective

Restore the source-grounded composite style of Figure 1 while removing the
unclean screenshot edges and reducing visual monotony in interfaces I1–I5. The
figure must explain the proof-to-payload gap, the five SHTPC interfaces, and the
end-to-end guarantee at IEEE double-column size.

## Approved direction

Use the restrained hybrid composition designated A1. Preserve the location
heatmap and the VDAF aggregation skeleton. Use tightly cropped published
components inside the interface cards, but retain manuscript-native labels,
equations, card borders, numbering, and scope statements.

## Source set

Only the following three CC BY 4.0 PoPETs papers provide embedded visual
components.

1. Hannah Davis, Christopher Patton, Mike Rosulek, and Phillipp Schoppmann,
   “Verifiable Distributed Aggregation Functions,” PoPETs 2023(4), Figure 1,
   DOI 10.56553/popets-2023-0126.
2. Sayan Biswas and Catuscia Palamidessi, “PRIVIC: A privacy-preserving method
   for incremental collection of location data,” PoPETs 2024(1), Figures 1 and
   2, DOI 10.56553/popets-2024-0033.
3. Dimitris Mouris, Pratik Sarkar, and Nektarios Georgios Tsoutsos, “PLASMA:
   Private, Lightweight Aggregated Statistics against Malicious Adversaries,”
   PoPETs 2024(3), Figure 2, DOI 10.56553/popets-2024-0064.

## Panel structure

The three-region structure remains unchanged.

- Left region presents two independently accepted objects. A cropped PRIVIC
  location component represents trajectory admission. A tightly cropped VDAF
  input component represents locally valid aggregation input. The region ends
  with `p != q` and states that the trajectory refers to `p` while the payload
  contributes to `q`.
- Center region is the visual focus and receives the largest width. It contains
  five interface cards in two rows. I1–I3 occupy the upper row. I4 and I5 occupy
  the lower row. A short binding statement spans the bottom without repeating
  every interface description.
- Right region retains the consistency equation, the PRIVIC heatmap component,
  the unchanged downstream release, and the explicit claim scope.

## Interface-to-component mapping

- I1 Accepted state uses the state-bearing left portion of VDAF Figure 1. The
  crop may retain `st_init`, Shard, and the first preparation transition. The
  manuscript label states accepted-state continuity. The figure does not claim
  that the VDAF state is itself the SHTPC predecessor commitment.
- I2 Hidden trajectory uses a cropped PRIVIC location relation. Source titles,
  axes labels, and color-bar text are removed where possible. The manuscript
  label supplies hidden-coordinate and ADWC semantics.
- I3 Derived primary uses the grid and highlighted-cell portion of the same
  PRIVIC source. It is paired with `p_t = Grid(x_t)`. The component is not
  presented as experimental evidence.
- I4 Delivered-package binding uses the VDAF Shard, two preparation paths,
  aggregation, and Unshard structure. Repeated protocol detail and peripheral
  variables are cropped out. The accompanying text distinguishes the proof's
  package commitments from the packages actually received by A and R.
- I5 Equal authenticated sets uses the server-session attestation relationship
  from PLASMA Figure 2. SHTPC-specific text states that A and R must expose the
  same authenticated report identifiers. The PLASMA third-server topology is
  not relabeled as an SHTPC participant topology.

## Crop and styling rules

- Crop from 600 dpi page renders or directly embedded vector graphics.
- Remove page headers, figure captions, surrounding prose, cut-off arrows, and
  partial neighboring diagrams.
- Preserve the source component's internal geometry and aspect ratio.
- Do not redraw or AI-generate the embedded source components.
- Use a white background, Times-compatible typography, fixed blue, green, and
  red accents, uniform rounded-card borders, and equal I1–I5 number badges.
- Source components must not contain text that becomes meaningless or
  unreadable at final paper size. When a label is not essential, crop it out
  instead of shrinking it.

## Semantic wording constraints

The I4 summary uses the following distinction.

`The proof binds authenticated package commitments. Each Aggregator verifies
the package actually received against its corresponding commitment.`

The left failure summary uses the following wording.

`Both local checks may accept. The accepted trajectory refers to p, but the
accepted payload contributes to q.`

The scope uses parallel noun phrases.

- Post-enrollment semantic consistency.
- Physical presence or truthful genesis.
- Trajectory anonymity or unlinkability.
- Security against a malicious Shuffler.
- Privacy under A/R collusion.

## Attribution

No attribution line is placed inside the image. The figure caption cites the
three source papers in one final sentence. The durable provenance record lists
the paper, exact figure and PDF page, crop filename, license, and the semantic
role assigned to each component.

## Acceptance criteria

1. The figure contains no AI-generated bitmap component.
2. Every embedded component traces to one of the three approved papers.
3. No crop contains page headers, source captions, body-text fragments, or
   clipped neighboring graphics.
4. I1–I5 read as one visual family despite using source components.
5. The I4 wording distinguishes proof commitments, delivered packages, and
   reconstructed shares.
6. The full figure remains readable at its actual IEEE double-column size.
7. The PDF keeps its aspect ratio and contains no LaTeX overfull box, undefined
   citation, or missing-resource warning.
8. The manuscript caption contains complete attribution, while the image itself
   contains no CC BY footer.
