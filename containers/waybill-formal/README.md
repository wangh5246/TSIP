# WayBill formal container

Build the pinned Linux x86_64 image from the repository root:

```bash
docker buildx build \
  --provenance=false \
  --platform linux/amd64 \
  --load \
  --tag waybill-formal:local \
  --file containers/waybill-formal/Dockerfile \
  --build-arg WAYBILL_GIT_COMMIT="$WAYBILL_GIT_COMMIT" \
  --build-arg WAYBILL_GIT_TREE="$WAYBILL_GIT_TREE" \
  --build-arg WAYBILL_CODE_MANIFEST_SHA256="$WAYBILL_CODE_MANIFEST_SHA256" \
  --build-arg WAYBILL_PROTOCOL_SHA256="$WAYBILL_PROTOCOL_SHA256" \
  .
```

Record the immutable image ID and registry digest before a formal run. The
target-host preflight must compare the observed digest with the protocol
receipt; a tag alone is not sufficient.

For an Apptainer site, first make the OCI image available to Apptainer, then:

```bash
apptainer build waybill-formal.sif containers/waybill-formal/Apptainer.def
apptainer inspect --json waybill-formal.sif
```

The image contains the exact formal execution source under `/work` plus an
immutable `/opt/waybill/release-bindings.json` record. Formal jobs must not call
host Python or bind a host checkout over `/work`. Use the generated Slurm
arrays, which bind the SIF SHA-256 and release OCI digest, isolate networking,
hide host filesystems, expose only the run directory read-write, mount the
prepared corpus, canonical-instance corpus, and PTAU read-only, and fail closed
if the runtime or embedded source binding differs from the sealed run.
