# RiseFL MVP Deployment

## Prerequisites

- Docker Desktop is installed and running.
- The workspace root is `/Users/wanghao/Desktop/risefl_mvp`.
- `.env` exists. You can copy values from `.env.example` if needed.

## Start The Stack

First build and start all services:

```bash
cd /Users/wanghao/Desktop/risefl_mvp
DO_BUILD=1 bash script/deploy_stack.sh
```

For later restarts without rebuilding images:

```bash
cd /Users/wanghao/Desktop/risefl_mvp
DO_BUILD=0 bash script/deploy_stack.sh
```

This starts:

- `shuffler`
- `aggregator_a`
- `aggregator_r`
- `decoder`
- `client_sim`

The deploy script waits for service health checks and prints the effective runtime config.

## Validate Deployment

Run the smoke check:

```bash
cd /Users/wanghao/Desktop/risefl_mvp
bash script/p0_smoke_check.sh
```

If the stack is healthy, this should end with:

```text
P0 smoke check passed
```

## Run One End-To-End Round

```bash
cd /Users/wanghao/Desktop/risefl_mvp
bash script/run_one_round.sh
```

## Health Endpoints

- `http://localhost:8001/health`
- `http://localhost:8002/health`
- `http://localhost:8003/health`
- `http://localhost:8010/health`

## Useful Commands

Show service status:

```bash
docker compose ps
```

Tail logs:

```bash
docker compose logs -f shuffler
docker compose logs -f aggregator_a
docker compose logs -f aggregator_r
docker compose logs -f decoder
docker compose logs -f client_sim
```

Stop the stack:

```bash
docker compose down
```

## Common Issues

If you see `Cannot connect to the Docker daemon`, start Docker Desktop first.

If a service does not become healthy, inspect:

```bash
docker compose ps
docker compose logs --tail=100 shuffler
docker compose logs --tail=100 aggregator_a
docker compose logs --tail=100 aggregator_r
docker compose logs --tail=100 decoder
```

If you changed Dockerfiles or dependencies, rebuild:

```bash
DO_BUILD=1 bash script/deploy_stack.sh
```
