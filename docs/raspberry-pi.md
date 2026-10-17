# Raspberry Pi deployment

Use a 64-bit Raspberry Pi OS Lite installation. No host desktop or monitor is necessary: the desktop runs inside the student image. Suggested pilot: Pi 5, 8 GB RAM, active cooling, suitable power supply, SSD and Ethernet. A 4 GB Pi should start with only one or two sessions until measured.

1. Use Raspberry Pi Imager to set a hostname, trusted SSH user/key, network and timezone. Boot and SSH to the Pi.
2. Check architecture, RAM and storage:

```bash
uname -m
cat /etc/os-release
free -h
df -h
sudo apt update
sudo apt install -y git curl ca-certificates
```

`uname -m` should report `aarch64`. Install Docker Engine and the Compose plugin using [Docker's Debian instructions](https://docs.docker.com/engine/install/debian/), matching the underlying Debian release for Raspberry Pi OS. Do not follow the separate 32-bit Pi package path for this ARM64 deployment.

```bash
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Use `sudo docker` or grant Docker access only to a trusted operator using Docker's post-install guide. Docker-group membership is effectively host-root access. The README commands assume your operator can run `docker`.

3. Follow the README quick start, with the appropriate desktop image and `MAX_SESSIONS`.
4. Set up the host tunnel to loopback port 8080; no router port forwarding is needed for this design.
5. Check `docker stats`, temperatures/throttling (`vcgencmd get_throttled` where available), desktop startup time and memory during real exercises. Leave room for Linux, Docker, the tunnel and filesystem cache.

If Docker warns that memory/CPU cgroup limits are unavailable, resolve host cgroup configuration before admitting students. Do not treat unenforced limits as safe capacity.

An API container restarts through Compose, but dynamically created student containers have no restart policy in this version. A host reboot may leave session records whose desktops no longer run. Drain/end sessions before maintenance; restart recovery/reconciliation is future work.
