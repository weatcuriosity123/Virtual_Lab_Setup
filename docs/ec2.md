# Deploy the lab on AWS EC2

This is a proposed deployment path using the same single-host application. It has not been benchmarked on EC2. Use a separate test hostname before moving a class.

## Instance and network

- Use Ubuntu Server 24.04 LTS, with a matching CPU architecture: x86_64 for amd64 images, or ARM64 for Graviton images.
- Start a pilot with approximately 4 vCPU and 8–16 GiB RAM, 40 GB or more encrypted gp3 EBS, and `MAX_SESSIONS=4`. This is a sizing hypothesis, not a guarantee. A general-purpose non-burstable instance is preferable for sustained desktop encoding. T-family instances use CPU credits; benchmark credit depletion and potential surplus charges if you choose them.
- Select a region close to students. Measure round-trip latency and streaming quality.
- Configure an SSH key pair. Permit inbound TCP 22 only from the administrator's public IP, or use a properly configured Systems Manager path.
- With a host-side Cloudflare Tunnel, no inbound 80/443/8080/8000/3000/3001 rule is needed for lab traffic. Keep the Compose loopback binding.
- The instance needs outbound connectivity for DNS, package/image downloads and Cloudflare Tunnel. Start with the normal outbound configuration for your pilot; if restricting egress, follow Cloudflare's current connector firewall requirements.
- A public subnet with an internet gateway and public address is a simple pilot route. A private subnet needs an appropriate outbound route such as NAT. NAT, public IPv4, EBS and transfer can add charges.
- Require IMDSv2; avoid giving the instance an IAM role with unnecessary privileges. Container network access to metadata and other services must be reviewed before untrusted student use.

## Installation

SSH from your local terminal (replace the key path and public address):

```bash
ssh -i lab-key.pem ubuntu@EC2_PUBLIC_IP
```

On Linux/macOS clients, restrict the private key's file permissions before use; on Windows use appropriate file ACLs. Never upload the private key to GitHub.

On EC2:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates
uname -m
```

Follow [Docker's official Ubuntu repository installation](https://docs.docker.com/engine/install/ubuntu/) to install Docker Engine, Buildx and the Compose plugin, then verify:

```bash
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Provide the student image using [the image guide](student-image.md). An ARM64 Pi image cannot run natively on an x86_64 EC2 instance. Prefer native builds rather than emulation for interactive classrooms.

Follow the root README quick start. Configure a new hostname in `PUBLIC_BASE_URL`, a new private class code, and a cap of four or lower. Install `cloudflared` on this instance, connect a separate tunnel and point its hostname to `http://127.0.0.1:8080`.

Test health, start, desktop login, timer activation, resume, End Lab, inactivity and feedback before publishing the hostname to students. Do not attach a new empty EC2 host as another connector for the Pi's existing tunnel: sessions are host-local and requests may reach the wrong host.

## Operation and migration

- Enable cost budgets/alerts. Review current regional instance, EBS, public IPv4 and network pricing; no free-tier assumption is made here.
- Monitor host memory with an agent or host metrics: default EC2 metrics alone do not provide all memory/filesystem observations needed for desktop sizing.
- Schedule maintenance after sessions end. Back up SQLite consistently and keep `.env`/tunnel secrets out of snapshots intended for sharing.
- To migrate from Pi, finish current sessions, reproduce the application and image on EC2, validate under a test hostname, then switch the public routing. In-memory desktops and tmpfs home directories are not migrated by copying SQLite.
- An Auto Scaling Group does not make this application multi-host by itself; see [scaling](scaling.md).

Sources: [security-group rules](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html), [CPU credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html), [Docker Ubuntu install](https://docs.docker.com/engine/install/ubuntu/).
