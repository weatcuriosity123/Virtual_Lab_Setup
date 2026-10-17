# HTTPS access through Cloudflare Tunnel

Use a domain managed in Cloudflare and install `cloudflared` on the Docker host using the [official connector documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/). Choose the binary matching ARM64 or amd64.

The current lab origin is **http://127.0.0.1:8080**, not the old standalone desktop port 3000/3001. Route the whole hostname so `/`, `/api/` and `/s/` remain on one origin. This is necessary for iframe activity and picture checks.

For a dashboard-managed tunnel:

1. Create a tunnel and install its connector as a host system service using the generated instructions.
2. Add the public hostname (for example `lab.example.com`) with HTTP origin `127.0.0.1:8080`.
3. Set the same HTTPS origin in backend `.env` as `PUBLIC_BASE_URL`.
4. Verify `systemctl status cloudflared` and `curl --fail http://127.0.0.1:8080/api/health`.
5. Test the portal from a separate browser/device.

For a locally managed tunnel, `cloudflare/config.example.yml` shows the ingress format. Substitute your UUID, real credential-file path and hostname, create the DNS route and install the service following the current official guide. Do not mix dashboard and local management accidentally. Tokens/credential JSON files belong outside Git.

Keep the connector on the host for this example. If it runs in another container, `127.0.0.1` points to that container and this origin address will not work.

Cloudflare Access can add identity-based access for the whole hostname. Test its login/session-expiry behaviour with the iframe and WebSocket stream. The class code is admission to create a session; it is not a full identity system or a replacement for a secure application gateway. Avoid caching authenticated API/session responses.
