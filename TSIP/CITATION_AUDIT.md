# TSIP Heatmap Citation Audit

Audit date: 2026-07-13. Metadata and claim support were checked against
publisher pages, standards-body records, official dataset pages/guides, or the
original paper page. Search-result snippets are not evidence. "Checked" means
the manuscript paraphrase stays within the source's stated scope; it does not
mean the cited work implements SHTPC.

| Bib key | Primary source | Metadata verified | Supported manuscript claim | Quote/paraphrase checked | Status/action |
|---|---|---|---|---|---|
| `Yuan2010Tdrive` | [ACM DOI](https://doi.org/10.1145/1869790.1869807), [Microsoft guide](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/User_guide_T-drive.pdf) | Authors, title, venue, pages 99-108, DOI | T-Drive provenance and required citation | Yes; dataset-scale wording checked against the official guide | Verified |
| `Yuan2011Driving` | [ACM DOI](https://doi.org/10.1145/2020408.2020462), [Microsoft guide](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/User_guide_T-drive.pdf) | Authors, title, KDD 2011, pages 316-324, DOI | Second citation required by the T-Drive guide | Yes; used for provenance, not a method baseline | Added |
| `Zheng2008Understanding` | [ACM DOI](https://doi.org/10.1145/1409635.1409677), [GeoLife guide](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/User20Guide-with20labels.pdf) | Authors, title, UbiComp 2008, pages 312-321, DOI | Citation required by the GeoLife 1.3 guide | Yes; used for provenance and mobility context | Added |
| `Zheng2009Mining` | [ACM DOI](https://doi.org/10.1145/1526709.1526816), [GeoLife guide](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/User20Guide-with20labels.pdf) | Authors, title, WWW 2009, pages 791-800, DOI | Citation required by the GeoLife 1.3 guide | Yes; used for provenance and trajectory context | Added |
| `Zheng2010GeoLife` | [Microsoft publication](https://www.microsoft.com/en-us/research/publication/geolife-a-collaborative-social-networking-service-among-user-location-and-trajectory/) | Corrected authors to Zheng, Xie, and Ma; journal, volume, pages | GeoLife provenance and corpus description | Yes; manuscript conservatively says 17K+ trajectories because official materials contain inconsistent exact counts | Corrected metadata |
| `MoreiraMatias2015Porto` | [UCI record](https://archive.ics.uci.edu/dataset/339/taxi%2Bservice%2Btrajectory%2Bprediction%2Bchallenge%2Becml%2Bpkdd%2B2015) | Title, year, DOI 10.24432/C55W25, CC BY 4.0 | Porto provenance, 442 taxis, and official licensing | Yes; author list uses `et al.` because the official record contains two abbreviated creator entries | Added |
| `Bracciale2014Rome` | [CRAWDAD record](https://crawdad.org/~crawdadarchive/roma/taxi/20140717/), [DOI](https://doi.org/10.15783/C7QC7M) | Six contributors, version date, DOI | Rome provenance, approximately 320 taxis over 30 days | Yes; no stronger collection or representativeness claim is made | Added |
| `Dwork2006calibrating` | [Springer DOI](https://doi.org/10.1007/11681878_14) | Authors, title, TCC 2006, pages, DOI | Sensitivity-calibrated differential privacy foundation | Yes; no implementation attribution | Verified |
| `Dwork2014algorithmic` | [Publisher monograph](https://doi.org/10.1561/0400000042) | Authors, title, volume, pages, DOI | DP definitions, composition, and sensitivity background | Yes | Verified |
| `Balle2019privacy` | [Springer DOI](https://doi.org/10.1007/978-3-030-26951-7_22) | Corrected full author list, title, pages, DOI | Shuffle-model privacy amplification design point | Yes; not presented as an SHTPC implementation | Corrected metadata |
| `Cheu2019distributed` | [Springer DOI](https://doi.org/10.1007/978-3-030-17653-2_13) | Corrected fifth author, title, pages, DOI | Distributed DP via shuffling | Yes | Corrected metadata |
| `Bittau2017Prochlo` | [Google Research publication](https://research.google/pubs/prochlo-strong-privacy-for-analytics-in-the-crowd/), [ACM DOI](https://doi.org/10.1145/3132747.3132769) | Corrected ten-author list, title, SOSP pages, DOI | Encode-shuffle-analyze separation in Prochlo | Yes; admission limits remain the manuscript's analysis | Corrected metadata |
| `Shamsabadi2025Nebula` | [ACM DOI](https://doi.org/10.1145/3719027.3744789) | Authors, title, CCS 2025, pages 498-512, DOI | Private histogram estimation design point | Yes; no proof-to-payload attribution | Verified |
| `Corrigan2017Prio` | [USENIX paper](https://www.usenix.org/conference/nsdi17/technical-sessions/presentation/corrigan-gibbs) | Authors, title, NSDI 2017, pages | Private aggregate statistics with report validity checks | Yes; SHTPC's stateful trajectory relation is not attributed to Prio | Verified |
| `Boneh2021Poplar` | [IEEE S&P program](https://www.ieee-security.org/TC/SP2021/program-papers.html) | Authors, title, pages 762-776; corrected DOI to 10.1109/SP40001.2021.00048 | Private heavy-hitters/VDAF-related design point | Yes | Corrected DOI |
| `Bell2023ACORN` | [USENIX paper](https://www.usenix.org/conference/usenixsecurity23/presentation/bell) | Authors, title, pages 4805-4822 | Input validation for secure aggregation | Yes; used as a design point, not a drop-in baseline | Verified |
| `Barnes2026VDAF` | [IETF Datatracker](https://datatracker.ietf.org/doc/draft-irtf-cfrg-vdaf/) | Draft authors, draft-20 identifier, 2026-06-24 date | Current VDAF interface/specification design point | Yes; explicitly treated as an Internet-Draft and Work in Progress, not a standard | Verified and scoped |
| `Groth2016pairing` | [Springer DOI](https://doi.org/10.1007/978-3-662-49896-5_11) | Author, title, EUROCRYPT pages, DOI | Pairing-based preprocessing SNARK construction | Yes; production ceremony is not inferred | Verified |
| `Grassi2021Poseidon` | [USENIX paper](https://www.usenix.org/conference/usenixsecurity21/presentation/grassi) | Corrected fifth author, title, pages | Circuit-oriented Poseidon hash design | Yes | Corrected metadata |
| `Albrecht2016MiMC` | [Springer DOI](https://doi.org/10.1007/978-3-662-53887-6_7) | Corrected author list, title, pages, DOI | Low-multiplicative-complexity MiMC design | Yes | Corrected metadata |
| `Goldwasser1989ZK` | [SIAM DOI](https://doi.org/10.1137/0218012) | Authors, title, journal metadata, DOI | Foundational zero-knowledge definition | Yes; only foundational attribution | Verified |

## Audit Decisions

- Dataset claims cite every publication required by the official T-Drive and
  GeoLife guides, plus the official Porto and Rome records.
- VDAF, shuffle-DP, secure-aggregation, and ZK works remain analytical design
  points unless the evaluation runs their implementations under the same
  contract. The manuscript does not call them drop-in empirical baselines.
- The current Groth16 relation and performance evidence are repository facts,
  not claims supplied by the Groth citation.
- Any new technical or dataset claim added after this checkpoint must add or
  update a row before submission.
