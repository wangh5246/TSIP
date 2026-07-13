# TSIP Heatmap Data Notice

This notice covers the five inputs used by the V4 Heatmap evaluation. The
repository release policy is deliberately stricter than the most permissive
individual dataset license: no raw or row-level prepared trajectories from the
four real datasets are distributed. Reproducers must obtain each dataset from
its official source and accept its terms. The repository contains preparation
code, non-row-level manifests, aggregate receipts, tables, and figures.

## T-Drive
- Type: Real-world taxi GPS trajectories collected in Beijing from 10,357 taxis during February 2-8, 2008.
- Owner/source: Microsoft Research Asia.
- Official URL: https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/ ; official user guide: https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/User_guide_T-drive.pdf
- Required citation: Jing Yuan et al., "T-Drive: Driving Directions Based on Taxi Trajectories," GIS 2010, DOI 10.1145/1869790.1869807; Jing Yuan et al., "Driving with Knowledge from the Physical World," KDD 2011, DOI 10.1145/2020408.2020462.
- License/terms: Microsoft Research License Agreement in the official user guide; use is limited to non-commercial research and the agreement controls the dataset and derivative works.
- Redistribution: The agreement prohibits distributing the dataset or derivative works. Raw and row-level prepared T-Drive records must not be committed or released.
- Local preprocessing: `TSIP_heatmap_version/runtime/experiments-heatmap/prepare_five_dataset_heatmap_inputs.py` parses taxi files, splits traces at gaps over 120 seconds, projects coordinates locally, creates non-overlapping ten-window records on a 100 by 100 grid with 100 m cells, and selects 1,000 source records without bootstrap.
- Repository contents: Preparation code, `five_dataset_inputs/manifest.json`, and aggregate experiment evidence only; no raw or row-level prepared T-Drive data.

## GeoLife
- Type: Real-world multi-modal GPS trajectories from 182 users collected between April 2007 and August 2012.
- Owner/source: Microsoft Research Asia.
- Official URL: https://www.microsoft.com/en-us/research/project/geolife-building-social-networks-using-human-location-history/tools/ ; official version 1.3 user guide: https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/User20Guide-with20labels.pdf
- Required citation: Yu Zheng et al., "Mining Interesting Locations and Travel Sequences from GPS Trajectories," WWW 2009, DOI 10.1145/1526709.1526816; Yu Zheng et al., "Understanding Mobility Based on GPS Data," UbiComp 2008, DOI 10.1145/1409635.1409677; Yu Zheng, Xing Xie, and Wei-Ying Ma, "GeoLife: A Collaborative Social Networking Service among User, Location and Trajectory," IEEE Data Engineering Bulletin 33(2), 2010.
- License/terms: Microsoft Research License Agreement supplied with the official dataset guide; use is limited to non-commercial research and the agreement controls the dataset and derivative works.
- Redistribution: The agreement prohibits distributing the dataset or derivative works. Raw and row-level prepared GeoLife records must not be committed or released.
- Local preprocessing: `TSIP_heatmap_version/runtime/experiments-heatmap/prepare_five_dataset_heatmap_inputs.py` parses `.plt` traces, splits traces at gaps over 120 seconds, projects coordinates locally, creates non-overlapping ten-window records on a 100 by 100 grid with 100 m cells, and selects 1,000 source records without bootstrap.
- Repository contents: Preparation code, `five_dataset_inputs/manifest.json`, and aggregate experiment evidence only; no raw or row-level prepared GeoLife data.

## Porto
- Type: Real-world taxi trajectories recorded by 442 taxis operating in Porto, Portugal.
- Owner/source: UCI Machine Learning Repository; dataset creators Luis Moreira-Matias, Michel Ferreira, Joao Mendes-Moreira, and additional creators listed by UCI.
- Official URL: https://archive.ics.uci.edu/dataset/339/taxi%2Bservice%2Btrajectory%2Bprediction%2Bchallenge%2Becml%2Bpkdd%2B2015 ; DOI 10.24432/C55W25.
- Required citation: Moreira-Matias, Ferreira, Mendes-Moreira, et al., "Taxi Service Trajectory - Prediction Challenge, ECML PKDD 2015," UCI Machine Learning Repository, 2015, DOI 10.24432/C55W25.
- License/terms: Creative Commons Attribution 4.0 International (CC BY 4.0), as stated on the official UCI record.
- Redistribution: CC BY 4.0 permits sharing and adaptation with attribution, but this project does not distribute raw or row-level prepared Porto trajectories under its uniform real-data release policy.
- Local preprocessing: `TSIP_heatmap_version/runtime/script/prepare_eval_datasets.py` converts the official `train.csv.zip` POLYLINE records sampled at 15-second intervals into a local identity-period file; `prepare_five_dataset_heatmap_inputs.py` then creates ten-window, 1,000-record input without bootstrap on the fixed grid.
- Repository contents: Preparation code, `five_dataset_inputs/manifest.json`, and aggregate experiment evidence only; no raw or row-level prepared Porto data.

## Rome
- Type: Real-world taxi GPS traces collected from approximately 320 taxis in Rome over 30 days.
- Owner/source: CRAWDAD contributors Lorenzo Bracciale, Marco Bonola, Pierpaolo Loreti, Giuseppe Bianchi, Raul Amici, and Antonello Rabuffi.
- Official URL: https://crawdad.org/~crawdadarchive/roma/taxi/20140717/ ; DOI 10.15783/C7QC7M; CRAWDAD use guidance: https://crawdad.org/~crawdadarchive/faq.html
- Required citation: Lorenzo Bracciale et al., "CRAWDAD Dataset roma/taxi (v. 2014-07-17)," CRAWDAD, DOI 10.15783/C7QC7M.
- License/terms: CRAWDAD use guidance requires contributor citation, prohibits attempts to de-anonymize participants, and directs later users to acquire data from CRAWDAD.
- Redistribution: Do not re-share the dataset or row-level derivatives; direct reproducers to CRAWDAD and require them to accept the provider terms.
- Local preprocessing: `TSIP_heatmap_version/runtime/experiments-heatmap/prepare_five_dataset_heatmap_inputs.py` parses `Roma.txt`, splits traces at gaps over 120 seconds, projects coordinates locally, creates non-overlapping ten-window records on the fixed grid, and selects 1,000 source records without bootstrap.
- Repository contents: Preparation code, `five_dataset_inputs/manifest.json`, and aggregate experiment evidence only; no raw or row-level prepared Rome data.

## Synthetic
- Type: Repository-generated clustered random-walk mobility records.
- Owner/source: Generated by the TSIP Heatmap experiment code; no external dataset owner.
- Official URL: Repository script `TSIP_heatmap_version/runtime/experiments-heatmap/prepare_five_dataset_heatmap_inputs.py` is the canonical generator.
- Required citation: Cite the TSIP Heatmap paper and artifact; no external dataset citation is required.
- License/terms: Author confirmation required before redistribution.
- Redistribution: Author confirmation required before redistribution.
- Local preprocessing: The generator samples 120 hotspots and three anchors per user, produces clustered random walks for 1,000 users and ten windows, and uses seed 20260709 by default.
- Repository contents: Generator code, seed policy, non-row-level manifest, and aggregate evidence; generated row-level input remains local until the repository license is approved.

## Release Gate

The repository has no author-approved top-level license at this checkpoint.
Dataset terms do not grant a license to the project code. Release of project
code or synthetic row-level records therefore remains subject to the author
confirmation recorded in
`docs/submission/TSIP_HEATMAP_AUTHOR_CONFIRMATIONS.md`.
