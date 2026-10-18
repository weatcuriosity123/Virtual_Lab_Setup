# Network isolation: host trial before production rollout

## Observed pilot host (2026-10-18)

Docker 26.1.5 uses iptables-nft 1.8.11, with DOCKER-USER reached before Docker's
forwarding rules. Both bridge IPv4 and IPv6 filtering sysctls are enabled. The
current shared production bridge is 172.18.0.0/16, containing API and proxy and
student sessions when running. The host LAN is 192.168.29.0/24. The host has IPv6,
even though the production Docker network has EnableIPv6=false.

Production isolation is **not implemented by the trial script**; use the persistent
deployment section below after the trial passes. The trial proves
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

## Persistent deployment (single-host quota pilot)

The disposable trial passed on the Pi with explicit public DNS on 2026-10-18.
Persistent isolation is now implemented, but requires the live acceptance below.

End all labs before deployment. The second step briefly recreates the API/proxy;
keep your SSH session open. Neither step rebuilds the student image.

```bash
bash scripts/install-classrooms.sh "$HOME/linux-lab/backend"
sudo python3 scripts/manage-network-isolation.py install "$HOME/linux-lab/backend"
```

The installer requires the managed quota Compose override. It adds a separate
`compose.network-isolation.yml`, selected through COMPOSE_FILE in `.env`; it does
not replace the quota override. Future ordinary classroom updates retain this
selection. Do not rerun the quota installer blindly: it intentionally refuses a
custom COMPOSE_FILE. Review merges when upgrading that host service.

Student network: `linux-lab-students`, bridge `ll-students`, subnet
172.30.240.0/24, dynamic allocation 172.30.240.128/25. API and proxy additionally
attach at .2 and .3; their existing control network remains. Conflicting routes
or networks cause installation refusal. Public DNS 1.1.1.1/8.8.8.8 is configured
only for new student containers. Their IPv6 is disabled and NET_RAW/NET_ADMIN are
dropped. Webtop retains its other default Docker capabilities and existing
no-new-privileges setting. Wireshark can analyse capture files, but live capture,
raw sockets and network configuration exercises require a separately designed
restricted lab environment. Do not add capabilities to bypass these restrictions.

The root-only `linux-lab-network.service` installs scoped rules after Docker
starts and exposes a read-only Unix health endpoint. The API consults it before
allocating storage/creating a new desktop. Missing guard, changed rule order,
changed network configuration, unsafe attached endpoints or uncovered host routes
cause HTTP 503. Existing sessions are not continuously monitored or killed if a
host administrator manually flushes rules; this is admission protection, not an
instantaneous firewall-tampering watchdog. Host-root administration is trusted.
Do not flush rules or change routing while students are working.

Only API/proxy-initiated TCP connections to desktop port 3000 and established
student replies to those connections are allowed within the student subnet.
Student-initiated private-network traffic remains blocked even if a connection
was established during an earlier protection outage. Host INPUT is blocked
separately. The policy also records existing non-default IPv4 routes; rerun the
installer with no labs after intentional routing changes. Packet rules persist
in the kernel if the health service stops. Systemd reinstalls/checks rules after
boot/Docker start; no student restart policy is enabled. If rules need repair
while managed containers remain, the service refuses to loosen/replace them:
end labs, inspect the cause, then rerun installation. Saved volumes are untouched.

### Acceptance and diagnostics

```bash
systemctl is-active linux-lab-network.service
sudo python3 /usr/local/sbin/linux-lab-network-guard check
```

Start one persistent CSE lab. Verify desktop loading, keyboard/mouse, storage
banner and previous files, a DNS/HTTPS request and your normal programming tools.
This is the first real Webtop compatibility check for the capability/IPv6 changes.
If desktop startup fails, send API and student-container logs; do not disable the
guard or change capabilities as an improvised fix.

From the desktop terminal:

```bash
python3 - <<'PY'
import socket
from urllib.request import urlopen
for host, port in [('172.30.240.2',8000),('172.30.240.3',80),('172.30.240.1',22)]:
    try:
        with socket.create_connection((host,port),timeout=3):
            print('FAIL: reachable',host,port)
    except OSError:
        print('Blocked/unreachable:',host,port)
print('HTTPS status:',urlopen('https://example.com',timeout=15).status)
PY
```

Unreachable checks alone are not proof of firewall enforcement if no service
listens. Combine them with host rule counters and the already verified controlled
trial. A two-student actual-desktop test, WebSocket acceptance, admission-failure
test, Docker restart and host reboot tests remain required before declaring the
persistent policy accepted. On the 4 GiB Pi use tiny controlled peers for network
checks rather than raising supported classroom capacity without measurement.

To inspect failures:

```bash
sudo journalctl -u linux-lab-network.service -n 60 --no-pager
sudo iptables -nvL LL_STUDENTS
cd ~/linux-lab/backend
docker compose logs --tail=60 api
```

If a partial installation fails, the API may remain stopped deliberately. Inspect
the error and rerun the installer after resolving it, or use rollback. Never
manually flush the chain while labs are connected. The service does not change
SSH rules on the physical interface or global firewall policies.

### Rollback

End all labs first, including starting sessions. From the source checkout:

```bash
sudo python3 scripts/manage-network-isolation.py rollback "$HOME/linux-lab/backend"
```

Rollback restores the three original environment settings, recreates API/proxy
on their previous network, confirms no isolated endpoints remain, then disables
the guard and removes only its hooks/chain/network. Persistent homes and quota
service remain. The site will again have the previous **unisolated** network:
use it only for your own development until protection is reinstated. The saved
original-settings record is retained for repeat installation. Root-owned guard
configuration and source files remain for inspection; sysctl bridge filtering
stays enabled (it was enabled before installation).

### Backup and replacement-host recovery

The updated backup script includes the Compose isolation fragment, installed
network guard, policy configuration and original-settings record when present.
The existing Windows archive predates this feature. After acceptance, make and
transfer a new backup. On a replacement host restore the firewall/network service
and exact network addressing before enabling student admission. If COMPOSE_FILE
references the isolation fragment, restoring only the older Compose files is
insufficient. A whole-host recovery rehearsal is still pending.
