#!/usr/bin/env bash
set -e

docker compose up -d --build
bash ./run_one_round.sh

# 验收：latest dp 能输出
curl -s "http://localhost:8002/dump_latest_dp?epsilon=1.0&tau=3&tau2=3" | head
echo "M1 check done"
