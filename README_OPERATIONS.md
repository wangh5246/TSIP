# RiseFL MVP Operations

## Current Deployment State

The MVP has been deployed successfully on a remote Linux host and passed:

- service health checks
- stack bootstrap validation
- `P0 smoke check`

## Daily Commands

Start services:

```bash
cd ~/risefl_mvp
DO_BUILD=0 bash script/deploy_stack.sh
```

Smoke-check without rebuilding:

```bash
cd ~/risefl_mvp
BUILD_SERVICES=0 bash script/p0_smoke_check.sh
```

Run one business round:

```bash
cd ~/risefl_mvp
bash script/run_one_round.sh
```

Stop services:

```bash
cd ~/risefl_mvp
docker compose down
```

## Log Inspection

```bash
cd ~/risefl_mvp
docker compose ps
docker compose logs --tail=100 shuffler
docker compose logs --tail=100 aggregator_a
docker compose logs --tail=100 aggregator_r
docker compose logs --tail=100 decoder
docker compose logs --tail=100 client_sim
```

## Offline Image Workflow

If the server cannot access Docker Hub, build images locally and transfer them as a tar archive.

Local machine:

```bash
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose build
docker save -o risefl_mvp_images_amd64.tar \
  risefl_mvp-shuffler:latest \
  risefl_mvp-aggregator_a:latest \
  risefl_mvp-aggregator_r:latest \
  risefl_mvp-decoder:latest \
  risefl_mvp-client_sim:latest
```

Server:

```bash
docker load -i ~/risefl_mvp_images_amd64.tar
DO_BUILD=0 bash script/deploy_stack.sh
BUILD_SERVICES=0 bash script/p0_smoke_check.sh
```

## Known Constraints

- Current deployment is single-host.
- Current deployment depends on Docker Compose.
- Remote build may fail if the server cannot reach Docker Hub.
- Cross-architecture image transfer requires matching the target platform, such as `linux/amd64`.
