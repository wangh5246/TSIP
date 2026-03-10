# RiseFL MVP Server Deployment

## Goal

This document is for deploying the current MVP onto another machine, such as a Linux VM or a cloud host.

## 1. Prepare The Host

Install:

- Docker Engine or Docker Desktop
- Docker Compose plugin
- `curl`
- `git`

Optional but useful:

- `jq`

Clone the project:

```bash
git clone <your-repo-url> risefl_mvp
cd risefl_mvp
```

Create runtime config:

```bash
cp .env.example .env
```

Run host preflight:

```bash
bash script/check_deploy_host.sh
```

This checks:

- Docker CLI
- Docker daemon connectivity
- `.env`
- required zk artifacts
- basic port plan

## 2. Start The Stack

First deployment:

```bash
DO_BUILD=1 bash script/deploy_stack.sh
```

Later restarts:

```bash
DO_BUILD=0 bash script/deploy_stack.sh
```

## 3. Validate The Deployment

Smoke-check the full stack:

```bash
bash script/p0_smoke_check.sh
```

Run one business round:

```bash
bash script/run_one_round.sh
```

## 4. Verify Health Endpoints

```bash
curl -s http://localhost:8001/health
curl -s http://localhost:8002/health
curl -s http://localhost:8003/health
curl -s http://localhost:8010/health
```

## 5. Logs And Recovery

Service status:

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

Stop services:

```bash
docker compose down
```

Rebuild services:

```bash
DO_BUILD=1 bash script/deploy_stack.sh
```

## 6. Network Notes

If you need remote access from outside the host, open these ports in the server firewall or cloud security group:

- `8001`
- `8002`
- `8003`
- `8010`

If the services are only used internally on the server, keep those ports restricted.

## 7. Current Scope

This is still an MVP deployment:

- single host
- Docker Compose based
- no reverse proxy yet
- no TLS termination yet
- no persistent external database yet

That is acceptable for demo, validation, and paper reproduction. For production deployment, the next layer would be reverse proxy, TLS, secret management, and stronger observability.
