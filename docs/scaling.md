# Capacity testing and scaling

A visitor to the landing page, an API caller and a student operating a desktop have very different costs. A successful 100-user HTTP test does not prove 100 usable desktops. Current default admission is four sessions and there is no measured maximum in this repository.

## Measure before increasing capacity

Start at one real desktop, then two, then four. Use the actual lab apps and repeat for at least a full class period. Include simultaneous starts, typing, scrolling, application launches, package installation, disconnect/resume and termination.

Record:

- End-to-end start-to-usable-desktop time (p50/p95), rather than only POST /sessions latency.
- Browser interaction delay, dropped frames, disconnects and failed/retried starts.
- Host CPU, RAM, swap, network throughput, disk space/I/O and Pi thermal throttling.
- Per-container memory/CPU and OOM events; API error rate and expiry/cleanup lag.
- On burstable EC2, CPU credit balance and surplus-credit use.

Use `docker stats`, host metrics and browser observation. Locust can exercise admission/status/activity/feedback, but it does not render Selkies or simulate desktop video by default. Use real browser sessions or an explicitly designed browser automation workload for streaming. Run load generators on another machine.

Define acceptance thresholds before testing, for example a target p95 start time, maximum tolerable input delay, no OOM kills and no unexpected session loss. Choose the last consistently passing level with operational headroom.

## Estimate, then validate

A useful RAM-only upper bound is:

`floor((host RAM - measured host/service reserve) / measured peak memory per desktop)`

It is only a bound. CPU encoding, bandwidth or storage may saturate first. Current memory cap is 768 MiB per student; a workload that needs more may be killed rather than simply slow down. `/config` tmpfs and shared-memory usage consume memory; do not count their full configured capacities again as independent RAM reservations. Image layers and per-container writable layers also need disk space.

Example planning arithmetic, not a benchmark: 8 GiB minus a 2 GiB reserve divided by a 0.75 GiB limit gives eight memory slots. That does **not** establish eight usable desktops on a four-core Pi. Keep the configured cap lower until real use passes.

## Stage 1: scale one host

- Improve Pi cooling/power, use SSD/Ethernet, or move to a larger EC2 host.
- Prebuild the required applications in the image to avoid simultaneous downloads during class.
- Reduce unnecessary desktop resolution/frame rate after measuring usability.
- Raise `MAX_SESSIONS` only after measuring. Register a new classroom template with measured CPU/memory limits through the CLI; templates affect new containers.
- Add admission queues and per-user quotas before inviting large classes.

## Stage 2: remove single-host constraints

Not implemented yet. The API uses a process-local asyncio lock, SQLite, local Nginx files and one Docker socket. More Uvicorn workers or API replicas can bypass admission locking and race over shared state. Fixed container names also prevent simple Compose scaling.

Before multi-host deployment, implement:

1. Shared session metadata (for example PostgreSQL), transactional capacity reservations and idempotency across replicas.
2. A scheduler with per-node resource inventory and a stored owner-node ID for every session.
3. Authenticated worker agents or an orchestrator to create/delete desktops on the correct host.
4. Routing by session ID to its owner node; a generic load balancer alone cannot find the right desktop.
5. One coordinated expiry/reconciliation system that detects missing containers and cleans orphaned routes.
6. Durable credentials/feedback handling, metrics, admission rate limits and node draining.

Kubernetes or ECS may be candidates after this redesign; the current local Docker/Nginx implementation cannot be moved unchanged into an autoscaling fleet. Avoid exposing Docker TCP APIs publicly.

## Stage 3: autoscale the fleet

Use pending-session demand and free desktop slots, with CPU/RAM pressure, as scaling inputs. Prewarm nodes because image pulls and desktop startup take time. Drain nodes before scale-in, respect absolute session deadlines, and handle interrupted instances explicitly. Do not place ordinary classroom sessions on interruptible capacity without a recovery strategy.

If persistent home directories are introduced, define quotas, lifecycle/retention, encryption and identity separation. Database backups alone do not preserve live desktops. Budget for compute, disks, image storage and network traffic.
