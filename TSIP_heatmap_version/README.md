# TSIP Heatmap: Final V4 Source

This is the single retained implementation for the TSIP Heatmap release. It
contains the V4-paper circuit, Python runtime, JavaScript Poseidon bindings,
and the paper-k6 Groth16 development artifacts. Earlier protocol snapshots,
historical experiment scripts and receipts, local trajectory data, manuscripts,
and generated figures are deliberately excluded.

## Layout

- `circuits/`: final Circom relation (`tsip_main_v4_paper_k6.circom` and its base).
- `runtime/common/`: shared protocol, binding, payload, and accountability code.
- `runtime/client/`: client-side report and proof generation service.
- `runtime/shuffler/`: admission and verification service.
- `runtime/js/`: Poseidon worker and locked Node dependency manifest.
- `zk/v4_paper_k6/`: matching R1CS, WASM, proving key, and verification key.

## Quick integrity checks

The checks below validate the retained source:

```bash
python3 -m compileall -q runtime
node --check runtime/js/poseidon_worker.js
node --check runtime/js/tsip_v4_bindings.js
snarkjs r1cs info zk/v4_paper_k6/tsip_main_v4_paper_k6.r1cs
```

To install the runtime dependencies locally, use Python 3.10+ and Node 20:

```bash
python3 -m pip install -r runtime/client/requirements.txt -r runtime/shuffler/requirements.txt
npm ci --prefix runtime/js
circom circuits/tsip_main_v4_paper_k6.circom --r1cs --wasm \
  --output "$(mktemp -d)" -l runtime/js/node_modules
```

The two service images can be built from this directory:

```bash
docker build -f runtime/client/Dockerfile -t tsip-heatmap-client .
docker build -f runtime/shuffler/Dockerfile -t tsip-heatmap-shuffler .
```

The services require an aggregation/decoding deployment and deployment-specific
environment variables; those operational integrations and all experiment data
are intentionally outside this source-only release.

## Security note

`zk/v4_paper_k6` uses the checked-in development proving setup. It is useful for
reproducing the bundled relation, but it is not a production multi-party setup
and must not be presented as one.

## License

No license has been selected yet. Add the project owner's chosen OSI-approved
license before making the repository public.
