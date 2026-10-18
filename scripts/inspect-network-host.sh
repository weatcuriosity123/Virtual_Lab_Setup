#!/usr/bin/env bash
# Read-only inspection on the Docker host. No firewall or network mutations.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo: bash scripts/inspect-network-host.sh [network-name]' >&2
  exit 1
fi
lab_network=${1:-linux-lab-net}
printf '\nDocker and kernel:\n'
docker version --format 'Server={{.Server.Version}}'
uname -r
printf '\nSelected network configuration (no environment or credentials):\n'
docker network inspect "$lab_network" | python3 -c '
import json,sys
n=json.load(sys.stdin)[0]
print(json.dumps({k:n.get(k) for k in ("Name","Id","Driver","Internal","EnableIPv6","IPAM","Options")},indent=2))
for c in (n.get("Containers") or {}).values():
    name=c.get("Name", "")
    kind="student" if name.startswith("linux-lab-session-") else name
    print("Endpoint:",kind,"IPv4="+c.get("IPv4Address",""),"IPv6="+c.get("IPv6Address",""))
'
printf '\nBridge interfaces:\n'
ip -brief link show type bridge
printf '\nHost IPv4 routes:\n'
ip -4 route show
printf '\nHost IPv6 routes:\n'
ip -6 route show
printf '\nForwarding and bridge filtering:\n'
for key in net.ipv4.ip_forward net.ipv6.conf.all.forwarding net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables; do
  sysctl "$key" 2>/dev/null || echo "$key unavailable"
done
printf '\nFirewall tooling and Docker chains:\n'
for tool in iptables ip6tables; do
  if command -v "$tool" >/dev/null; then
    "$tool" --version
    for chain in DOCKER-USER FORWARD INPUT; do
      printf '\n%s %s:\n' "$tool" "$chain"
      "$tool" -S "$chain" 2>&1 || true
    done
  else
    echo "$tool unavailable"
  fi
done
printf '\nNative nftables table names:\n'
if command -v nft >/dev/null; then
  nft list tables 2>&1 || true
else
  echo 'nft unavailable'
fi
printf '\nFirewall service status:\n'
for service in ufw firewalld nftables; do
  printf '%s: ' "$service"
  systemctl is-active "$service" || true
done
printf '\nSelected Docker daemon firewall settings:\n'
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/etc/docker/daemon.json')
if p.exists():
    cfg=json.loads(p.read_text())
    print(json.dumps({k:cfg[k] for k in ('firewall-backend','iptables','ip6tables','ipv6','icc','ip-forward','ip-forward-no-drop','userland-proxy') if k in cfg},indent=2))
else:
    print('No /etc/docker/daemon.json; daemon may use defaults or command-line flags.')
PY
printf '\nInspection complete. No configuration was changed.\n'
