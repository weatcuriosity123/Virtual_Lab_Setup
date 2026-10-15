# Browser-Based Linux Desktop on Raspberry Pi or AWS EC2

Deploy a lightweight Linux desktop inside Docker and access it through a web browser using Cloudflare Tunnel and a custom HTTPS URL.

The project can run on a Raspberry Pi at home or an AWS EC2 virtual machine. The deployment steps are largely identical after the operating system is ready.

## 1. Architecture

```text
Web Browser
    |
    | HTTPS
    v
Cloudflare DNS and Tunnel
    |
    v
cloudflared on the host
    |
    v
Docker Container
    |
    v
Linux Desktop (XFCE)
```

### Technology stack

- **Host OS:** Raspberry Pi OS / Debian / Ubuntu Server
- **Cloud VM:** AWS EC2 with Ubuntu Server
- **Container runtime:** Docker Engine
- **Desktop environment:** XFCE through LinuxServer Webtop
- **Remote access:** Browser-based desktop interface
- **Public access:** Cloudflare Tunnel
- **URL security:** HTTPS and Cloudflare Access

## 2. Prerequisites

You will need:

- A Raspberry Pi with a suitable power supply and microSD card, or an AWS account with permission to create an EC2 instance.
- A Debian- or Ubuntu-based operating system.
- A Cloudflare account.
- A domain managed through Cloudflare.
- SSH access to the host.
- An internet connection.

For a lightweight deployment, use a 64-bit operating system. A Raspberry Pi with 4 GB RAM can be a practical starting point; an EC2 instance should have enough memory for the desktop applications you intend to run.

---

## 3. Choose a deployment environment

### Option A: Raspberry Pi

1. Install Raspberry Pi OS Lite (64-bit) or another supported 64-bit Debian-based OS.
2. Enable SSH during setup or configure it after installation.
3. Boot the Raspberry Pi and connect through SSH or its local terminal.

Example SSH command:

```bash
ssh <username>@<raspberry-pi-ip>
```

Replace the placeholders with your actual connection details.

### Option B: AWS EC2

1. Open the AWS EC2 console.
2. Launch an instance using a supported 64-bit Ubuntu Server image.
3. Choose an instance size appropriate for your workload.
4. Configure a key pair for SSH access.
5. Allow inbound SSH on port 22 from your trusted IP address.
6. Launch the instance and connect using your SSH key.

Example:

```bash
chmod 400 <private-key-file>.pem

ssh -i <private-key-file>.pem \
  <username>@<ec2-public-ip>
```

Use the SSH username supplied by the selected operating system image. For Ubuntu EC2 images, it is commonly `ubuntu`.

**Important:** Neither deployment requires a monitor, keyboard, nor a desktop environment installed directly on the host.

---

## 4. Update the host operating system

Run on either the Raspberry Pi or EC2 host:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y curl ca-certificates gnupg
```

Reboot if the system requests it:

```bash
sudo reboot
```

Reconnect over SSH after the host restarts.

Verify the operating system and architecture:

```bash
cat /etc/os-release
uname -m
```

Typical 64-bit architecture values include `aarch64` for Raspberry Pi and `x86_64` for many EC2 instances.

---

## 5. Install Docker Engine

Install Docker using its official installation script:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh
```

Enable Docker at startup:

```bash
sudo systemctl enable --now docker
```

Verify the installation:

```bash
sudo docker version
sudo docker info
```

Check that the Docker daemon is running:

```bash
sudo systemctl status docker --no-pager
```

Optional: allow your user to run Docker without `sudo`:

```bash
sudo usermod -aG docker "$USER"
```

Log out and back in for the group change to take effect. Membership in the Docker group grants powerful, effectively root-level access to the host, so only trusted users should receive it.

---

## 6. Create persistent storage

Create a directory for the desktop container's configuration and user data:

```bash
mkdir -p "$HOME/webtop-config"
```

This directory will be mounted inside the container so that supported configuration and user data can persist when the container is recreated.

---

## 7. Deploy the browser-based Linux desktop

Use the LinuxServer Webtop XFCE image:

```bash
sudo docker pull lscr.io/linuxserver/webtop:ubuntu-xfce
```

Create the container:

```bash
sudo docker run -d \
  --name linux-desktop \
  --restart unless-stopped \
  --security-opt seccomp=unconfined \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Etc/UTC \
  -p 127.0.0.1:3000:3000 \
  -p 127.0.0.1:3001:3001 \
  -v "$HOME/webtop-config:/config" \
  --shm-size=1gb \
  lscr.io/linuxserver/webtop:ubuntu-xfce
```

The configuration above:

- Uses an XFCE desktop environment.
- Runs the desktop inside Docker.
- Restarts the container automatically after a host reboot.
- Persists supported desktop data in a host directory.
- Publishes the web interfaces only on the host's loopback address.
- Avoids exposing the desktop ports directly to the local network or internet.

The Webtop image provides HTTP on port `3000` and HTTPS on port `3001` by default.

Check the container:

```bash
sudo docker ps
```

Inspect startup logs:

```bash
sudo docker logs --tail 100 linux-desktop
```

If the container fails to start, inspect the logs before proceeding.

---

## 8. Test the desktop locally

Run this on the host:

```bash
curl -I http://127.0.0.1:3000/
```

A successful HTTP response indicates that the local web interface is responding.

You can also test the HTTPS listener:

```bash
curl -k -I https://127.0.0.1:3001/
```

The `-k` option disables certificate verification for this local diagnostic only. Do not use it as a general approach to securing public HTTPS connections.

At this point, the desktop should be running locally, but it is not yet available through the public URL.

---

## 9. Install Cloudflare Tunnel (`cloudflared`)

Install the official `cloudflared` package for your host operating system and architecture by following the current Cloudflare installation instructions:

https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

Verify the installation:

```bash
cloudflared --version
```

Keep `cloudflared` on the host for this configuration. That allows the tunnel to reach the desktop through `127.0.0.1:3000`.

---

## 10. Create a Cloudflare Tunnel

1. Sign in to the Cloudflare dashboard.
2. Open the Zero Trust dashboard.
3. Navigate to **Networks → Tunnels** (the menu labels may vary).
4. Create a tunnel.
5. Give it a descriptive, non-personal name.
6. Choose the connector installation method for your operating system.
7. Follow Cloudflare's instructions to authenticate the host and run the connector.

For a locally managed tunnel, you can also authenticate and create a tunnel using the CLI:

```bash
cloudflared tunnel login
cloudflared tunnel create linux-desktop
```

The creation command returns a tunnel UUID. Record that value for the configuration below.

Do not publish the tunnel credentials JSON file or any tunnel token in the GitHub repository.

**Choose one tunnel-management method:** use the dashboard-managed connector or the locally managed configuration. Do not accidentally run duplicate connectors with conflicting configurations.

---

## 11. Configure the public hostname

For a locally managed tunnel, create the configuration directory and file:

```bash
sudo mkdir -p /etc/cloudflared
sudo nano /etc/cloudflared/config.yml
```

Add the following configuration, replacing the example hostname and UUID with your own values:

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: /root/.cloudflared/<TUNNEL-UUID>.json

ingress:
  - hostname: desktop.example.com
    service: http://127.0.0.1:3000
  - service: http_status:404
```

This routes incoming requests for the chosen hostname to the local Webtop HTTP listener.

The configuration assumes that the tunnel credentials file is stored at the specified path. If your credentials are elsewhere, update the path accordingly.

For example, if the credentials are stored in a different user's home directory, point `credentials-file` to that actual location rather than copying a placeholder path.

Validate the configuration:

```bash
sudo cloudflared tunnel \
  --config /etc/cloudflared/config.yml \
  ingress validate
```

Test which ingress rule matches the hostname:

```bash
sudo cloudflared tunnel \
  --config /etc/cloudflared/config.yml \
  ingress rule https://desktop.example.com
```

---

## 12. Route DNS to the tunnel

For a locally managed tunnel, create the DNS route:

```bash
cloudflared tunnel route dns \
  linux-desktop \
  desktop.example.com
```

Replace the example hostname with the actual hostname you intend to use.

If you manage the tunnel entirely through the dashboard, configure the public hostname there instead. Select the appropriate tunnel and use the following origin service:

```text
Type: HTTP
URL: 127.0.0.1:3000
```

The dashboard-managed hostname must point to the tunnel connected to the machine running the desktop container.

---

## 13. Run the tunnel as a system service

For the locally managed configuration, install the service:

```bash
sudo cloudflared \
  --config /etc/cloudflared/config.yml \
  service install
```

If the service already exists, inspect it before reinstalling it.

Start and enable the service:

```bash
sudo systemctl enable --now cloudflared
```

Check its status:

```bash
sudo systemctl status cloudflared --no-pager
```

Read recent logs:

```bash
sudo journalctl -u cloudflared -n 100 --no-pager
```

A healthy connector should establish connections to Cloudflare without repeatedly restarting.

---

## 14. Protect the public desktop with Cloudflare Access

A public hostname should not automatically mean an unrestricted desktop.

In the Cloudflare Zero Trust dashboard:

1. Open Access applications.
2. Create a self-hosted application.
3. Add the public desktop hostname.
4. Create an allow policy for approved users or email addresses.
5. Select an appropriate authentication method.
6. Test access using an authorized browser session.

Keep the hostname protected by Access before sharing it.

Do not expose Docker's management socket, SSH, or other administrative services through the same public hostname.

---

## 15. Access the desktop

Open the configured hostname in a web browser:

```text
https://desktop.example.com
```

Complete the Cloudflare Access authentication flow if it is enabled. After authorization, the browser should connect to the Webtop desktop.

Cloudflare provides the public HTTPS connection. The tunnel forwards traffic to the local HTTP service; a separate public IP or router port-forwarding rule is not required.

---

## 16. Troubleshooting

### Check Docker

```bash
sudo docker ps
sudo docker inspect linux-desktop
sudo docker logs --tail 100 linux-desktop
```

### Check the local web service

```bash
curl -I http://127.0.0.1:3000/
```

If this fails, resolve the container or port issue before investigating Cloudflare.

### Check the tunnel

```bash
sudo systemctl status cloudflared --no-pager
sudo journalctl -u cloudflared -n 100 --no-pager
```

### Investigate a Cloudflare 502 Bad Gateway

A 502 commonly indicates that Cloudflare cannot successfully reach the configured origin service.

Check these items in order:

1. Confirm the desktop container is running.
2. Confirm the local HTTP endpoint responds.
3. Confirm the hostname's origin service uses `http://127.0.0.1:3000`, not the HTTPS port with the wrong protocol.
4. Confirm the tunnel connector runs on the same host as the local service, or adjust the origin address if it runs elsewhere.
5. Confirm the ingress rule and hostname match.
6. Inspect the tunnel logs for connection errors.

For HTTPS origin testing on port `3001`, remember that the origin URL must use `https://`. A self-signed origin certificate may require additional origin TLS configuration. The simpler configuration in this guide uses HTTP on loopback and Cloudflare's HTTPS connection externally.

### Restart services when needed

```bash
sudo docker restart linux-desktop
sudo systemctl restart cloudflared
```

---

## 17. Useful maintenance commands

| Task | Command |
|---|---|
| View running containers | `sudo docker ps` |
| View desktop logs | `sudo docker logs --tail 100 linux-desktop` |
| Restart desktop | `sudo docker restart linux-desktop` |
| Stop desktop | `sudo docker stop linux-desktop` |
| Start desktop | `sudo docker start linux-desktop` |
| View tunnel status | `sudo systemctl status cloudflared --no-pager` |
| View tunnel logs | `sudo journalctl -u cloudflared -n 100 --no-pager` |
| Update the image | `sudo docker pull lscr.io/linuxserver/webtop:ubuntu-xfce` |

Pulling an updated image does not update an already-running container. Recreate the container using the same configuration and persistent volume after reviewing the image's release notes and backup requirements.

---

## 18. Security and operational considerations

- Keep the operating system and container image updated.
- Protect the desktop with Cloudflare Access.
- Do not commit credentials, tokens, private keys, or tunnel UUID-associated secret files to Git.
- Use persistent storage and back up important user data.
- Limit administrative access to the host.
- Monitor resource usage on low-memory devices.
- Use appropriate EC2 security-group rules and restrict SSH access.
- Do not treat a non-public origin port as a substitute for authentication.
- Review the Webtop image documentation before granting access to sensitive files or host resources.

## 19. Project structure

A simple repository can use this layout:

```text
browser-linux-desktop/
├── README.md
├── docker/
│   └── compose.yaml
├── cloudflare/
│   └── config.example.yml
├── scripts/
│   ├── install-docker.sh
│   └── check-status.sh
├── docs/
│   ├── raspberry-pi.md
│   ├── aws-ec2.md
│   ├── cloudflare-tunnel.md
│   └── troubleshooting.md
└── .gitignore
```

Keep real credentials and machine-specific configuration outside the repository. Commit only example configuration files with placeholders.

## 20. Expected outcome

After completing the deployment:

- A Linux desktop runs in a Docker container.
- The desktop is accessible through a browser.
- The host can be a Raspberry Pi or an AWS EC2 instance.
- Cloudflare Tunnel provides public HTTPS access without opening the desktop port directly to the internet.
- Cloudflare Access can restrict the desktop to authorized users.
- Desktop configuration and supported user data persist through a mounted host directory.

**Result:** a remotely accessible, containerized Linux desktop managed through a browser, with a deployment process that can be repeated on supported ARM64 and x86-64 Linux hosts.

## References

- Docker Engine: https://docs.docker.com/engine/install/
- LinuxServer Webtop: https://docs.linuxserver.io/images/docker-webtop/
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Cloudflare Access: https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/
- AWS EC2: https://docs.aws.amazon.com/ec2/
- Raspberry Pi documentation: https://www.raspberrypi.com/documentation/
