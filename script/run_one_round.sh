#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
run_one_round.sh is intentionally disabled for WayBill formal evidence.
Use script/waybill_formal.py init-run followed by stage-specific local or
Slurm arrays. A reduced "one round" cannot enter the paper aggregate.
EOF
exit 64
