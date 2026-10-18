# Network isolation: host trial before production rollout

## Observed pilot host (2026-10-18)

Docker 26.1.5 uses iptables-nft 1.8.11, with DOCKER-USER reached before Docker's
forwarding rules. Both bridge IPv4 and IPv6 filtering sysctls are enabled. The
current shared production bridge is 172.18.0.0/16, containing API and proxy and
student sessions when running. The host LAN is 192.168.29.0/24. The host has IPv6,
even though the production Docker network has EnableIPv6=false.

Production isolation is **not implemented by the trial script**. This step proves
the relevant packet paths on the actual kernel before moving live desktops.

## Disposable trial

Run from the source checkout with `sudo python3 scripts/test-network-isolation.py`.
It uses the existing local `backend-api` image; no image downloads/rebuilds and no
changes to the API, Compose, live desktops, global firewall policies or SSH.
Allow up to a few minutes. It makes HTTPS requests to https://example.com to
verify internet connectivity before and after filtering, with separate DNS and
HTTPS diagnostics. Test containers explicitly use 1.1.1.1 and 8.8.8.8 as upstream
resolvers to avoid inheriting a private router DNS address blocked by the policy.
These are per-container trial settings, not host or production DNS changes. If
the local network blocks public DNS, the baseline will fail before rules are added;
use the output to design an explicit permitted resolver path. Test containers are capped at 64 MiB each, have a
read-only root filesystem, run as UID 65534, and drop all capabilities.

The trial reserves `linux-lab-isolation-test`, bridge `ll-isotest`, subnet
172.30.250.0/24 and firewall chain `LL_ISOTEST`. It refuses overlapping host routes
or Docker networks and pre-existing named test resources. It establishes known
reachable peer/control HTTP listeners and a host TCP listener before filtering,
then verifies:

- Student-initiated TCP to a peer, simulated control service and host is blocked.
- Simulated proxy can initiate desktop TCP connections and receive replies.
- Student DNS/HTTPS access remains usable; IPv6 is disabled in test containers.
- Rules block private, loopback, link-local/metadata, CGNAT and multicast IPv4
  ranges for new forwarded connections. This is rule coverage, not a live test
  against every address range or arbitrary LAN device.

The chains are attached only to traffic arriving from the disposable bridge.
IPv4 host INPUT is blocked separately from forwarded traffic. IPv6 INPUT and
FORWARD traffic from the test bridge is dropped. Docker embedded DNS still uses
Docker's resolver; this is not DNS policy enforcement. Capability restrictions
help prevent raw-packet source spoofing; the production desktop's required
capabilities need separate compatibility validation.

Ordinary errors and Ctrl+C run cleanup, removing test containers before removing
firewall protection. The test is not persistent across reboot. A PASS is not a
production security certification or a full browser/WebSocket acceptance test.
Local unit tests cover rule scope, cleanup after failure and probe-error handling;
only the Pi trial can establish actual packet behavior.

## Cleanup after an interrupted test

If the process is killed or power is lost, inspect exact test resources first.
Never use `iptables -F` without a chain name or flush the host's ruleset. The
following removes only the reserved trial resources. Missing-resource errors are
expected if normal cleanup already removed part of the trial.

```bash
sudo docker rm -f ll-isotest-student-a ll-isotest-student-b ll-isotest-proxy
```

Only after confirming those containers are gone:

```bash
sudo iptables -w 5 -D DOCKER-USER -i ll-isotest -j LL_ISOTEST
sudo iptables -w 5 -D INPUT -i ll-isotest -j DROP
sudo ip6tables -w 5 -D FORWARD -i ll-isotest -j LL_ISOTEST
sudo ip6tables -w 5 -D INPUT -i ll-isotest -j LL_ISOTEST
sudo iptables -w 5 -F LL_ISOTEST
sudo iptables -w 5 -X LL_ISOTEST
sudo ip6tables -w 5 -F LL_ISOTEST
sudo ip6tables -w 5 -X LL_ISOTEST
sudo docker network rm linux-lab-isolation-test
```

## Production rollout gates

After the trial passes, implement a dedicated student bridge, reserved control
endpoints, capability restrictions compatible with Webtop, and host protection
that is installed before student admission. Refuse lab creation if protection is
missing; handle Docker/host restarts and changes to endpoint addressing. Preserve
API readiness checks, proxy HTTP/WebSockets and required internet access. Account
for IPv6 and local/public-address LAN routes. Test with two disposable student
sessions, reboot, then repeat denied/allowed flows. Provide rollback that ends labs
before removing protection. Do not simply copy test IP exemptions onto the current
shared production network.

Reference: https://docs.docker.com/engine/network/firewall-iptables/ describes
DOCKER-USER and the distinction between Docker forwarding and other host chains.
The pilot remains on Docker 26's iptables backend; no backend migration is proposed.
