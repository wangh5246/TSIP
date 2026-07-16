# WayBill formal container

Build the pinned Linux x86_64 image from the repository root:

```bash
docker buildx build \
  --provenance=false \
  --platform linux/amd64 \
  --load \
  --tag waybill-formal:local \
  --file containers/waybill-formal/Dockerfile \
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
