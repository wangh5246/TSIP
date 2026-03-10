#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

DO_BUILD="${DO_BUILD:-1}"
WAIT_TIMEOUT_SEC="${WAIT_TIMEOUT_SEC:-180}"
VALIDATE="${VALIDATE:-1}"
SERVICES=(shuffler aggregator_a aggregator_r decoder client_sim)

wait_for_service() {
  local service="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SEC))

  while (( SECONDS < deadline )); do
    local cid
    cid="$(docker compose ps -q "$service" 2>/dev/null || true)"
    if [[ -z "$cid" ]]; then
      sleep 2
      continue
    fi

    local health
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
    if [[ "$health" == "healthy" || "$health" == "running" ]]; then
      echo "healthy: $service"
      return 0
    fi

    if [[ "$health" == "exited" || "$health" == "dead" ]]; then
      echo "error: service $service is $health" >&2
      docker compose logs --tail=50 "$service" >&2 || true
      return 1
    fi
    sleep 2
  done

  echo "error: timed out waiting for $service" >&2
  docker compose ps >&2 || true
  docker compose logs --tail=50 "$service" >&2 || true
  return 1
}

print_health() {
  local name="$1"
  local url="$2"
  local body
  body="$(curl -fsS "$url")"
  echo "[$name] $body"
}

echo "== deploy stack =="
echo "root=$ROOT_DIR"
echo "build=$DO_BUILD wait_timeout=${WAIT_TIMEOUT_SEC}s validate=$VALIDATE"

if [[ "$DO_BUILD" == "1" ]]; then
  docker compose up -d --build "${SERVICES[@]}"
else
  docker compose up -d "${SERVICES[@]}"
fi

echo "== wait for health =="
for service in "${SERVICES[@]}"; do
  wait_for_service "$service"
done

if [[ "$VALIDATE" == "1" ]]; then
  echo "== health endpoints =="
  print_health "shuffler" "http://localhost:8001/health"
  print_health "aggregator_a" "http://localhost:8002/health"
  print_health "aggregator_r" "http://localhost:8003/health"
  print_health "decoder" "http://localhost:8010/health"
fi

echo "== effective config =="
bash script/print_effective_config.sh

echo "== next commands =="
echo "docker compose exec client_sim python client.py"
echo "bash script/run_one_round.sh"
