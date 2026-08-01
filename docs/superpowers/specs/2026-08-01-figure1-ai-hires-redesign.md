# Figure 1 Pure-AI High-Resolution Redesign

## Objective

Create a new AI-rendered Figure 1 that is clearer and more visually polished
than the current compact raster figure when placed at IEEE double-column width.

## Visual direction

- Use a restrained publication palette with navy blue for SHTPC bindings,
  emerald green for accepted outputs, warm red for the composition failure,
  charcoal text, and a white background.
- Preserve the three major sections and the compact 3+2 semantic-closure grid.
- Do not restore the previously removed connector arrows. The numbered cards
  and I1 through I5 labels identify the interfaces without implying execution
  order.
- Use consistent rounded cards, border weights, icon styles, internal padding,
  title sizes, and baseline alignment.
- Give the SHTPC semantic-closure panel the strongest visual hierarchy.

## Readability and resolution

- Render with crisp vector-like edges, large labels, high contrast, and minimal
  fine detail.
- Keep the aspect ratio near 1.5 to 1.
- Produce a project-local high-resolution PNG of at least 3072 by 2048 pixels.
- Ensure that all text remains legible after scaling to approximately 90 percent
  of IEEE double-column width.

## Content invariants

- Preserve the proof-to-payload gap, the five semantic interfaces, the A and R
  package distinction, equal-set validation, the DP release, and the claim
  boundary.
- Preserve the equations for same-primary derivation, package binding, and
  coordinate-to-aggregate consistency.
- Preserve the five claim-boundary exclusions.
- Do not add unsupported guarantees, logos, gradients, decorative backgrounds,
  or watermarks.

## Verification

- Inspect every technical label and equation against the manuscript.
- Reject outputs with misspellings, malformed mathematical symbols, duplicated
  cards, restored sequence arrows, or omitted claim-boundary items.
- Compile the paper and inspect the final Figure 1 page at publication size.
- Confirm that the PDF has no compilation errors, undefined references, or
  overfull boxes.
