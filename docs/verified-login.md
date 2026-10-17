# Verified student login with Cloudflare Access

This optional mode binds each new lab to a verified account and an explicit classroom membership. It is disabled by default. Configure and test it during maintenance, with no active or starting labs. Existing anonymous sessions have no owner and cannot be resumed after enforcement is enabled.

## 1. Install the updated application

Use a separate checkout of this release, then run:

```bash
bash scripts/install-classrooms.sh ~/linux-lab/backend
```

The upgrade script backs up source and the database, installs `identity.py` and the JWT dependency, and updates Nginx along with the API. Its name is retained for compatibility with the earlier classroom upgrade. It refuses to interrupt active/starting sessions. It does not enable Cloudflare login or edit `.env`.

The Nginx update is required: every generated `/s/<token>/` route now uses an internal `auth_request` to the API. This checks ownership before desktop HTTP requests and WebSocket handshakes. Internal desktop-service readiness probes remain host-side. Start the new API only with its matching Nginx configuration. Startup refreshes existing managed route files.

## 2. Configure Cloudflare Access

Create a self-hosted public-hostname Access application for the whole `vm.curiosity4u.in` hostname (or your own hostname), not only the root page. `/api/*` and `/s/*` must be covered too. Keep the host-side tunnel origin at `http://127.0.0.1:8080`.

Choose Google/Microsoft or another supported identity provider, or email one-time PIN for a small pilot. Add an Allow policy for your test users. Do not add a Bypass policy for the API or desktops. Use your chosen identity provider consistently. Test a permitted and a denied account in separate browser profiles before enrolling a class.

Record two values:

- Your team URL: `https://YOUR-TEAM.cloudflareaccess.com`.
- The Application Audience (AUD) tag of this Access application.

These are configuration identifiers, not the tunnel token or OAuth client secret. The backend verifies the Access token's RS256 signature, issuer, audience, expiry, application type, subject and email. A supplied email header alone never authorizes a request. Access forwards the signed assertion; students do not paste JWTs into the portal.

Use the official [Access application guide](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/) and [token validation guide](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/) for current dashboard navigation.

## 3. Enroll a student

The college/template/classroom must already exist. For the example PCCOER classroom:

```bash
cd ~/linux-lab/backend
docker compose exec api python classrooms.py member-add pccoer-linux --email student@example.com
```

Replace the example with the exact email the student's verified login will provide. Enrollment is per classroom; a student may be enrolled in more than one. Addresses are stored lowercase. No real student emails are seeded in GitHub. `classrooms.py list` now prints roster addresses; treat its output as private.

## 4. Enable enforcement

Edit `.env` on the Pi:

```env
AUTH_MODE=cloudflare
CF_ACCESS_TEAM_URL=https://YOUR-TEAM.cloudflareaccess.com
CF_ACCESS_AUD=YOUR_APPLICATION_AUD_TAG
ALLOW_LEGACY_CLASS_CODE=false
```

Then:

```bash
docker compose up -d --force-recreate api
docker compose restart proxy
docker compose exec proxy nginx -t
curl --fail http://127.0.0.1:8080/api/health
```

The health endpoint is exempt from backend identity checks so the operator can test locally. All other API endpoints require verified identity in this mode. Legacy shared-code admission is disabled in this mode regardless of the legacy setting. Classroom codes still select the classroom; membership decides eligibility.

Test the portal through the public HTTPS hostname. Open `/api/me` in that signed-in browser to verify the recognized email. Direct terminal requests to `/api/me` without an Access assertion should fail with 401; this is expected.

## 5. Acceptance checks

1. Allowed, enrolled account: sign in, enter its classroom code, launch and resume a lab. Verify the email shown on the landing page.
2. Allowed but unenrolled account: the same code must be rejected with 403.
3. Another enrolled account: even with the first student's ID and password, its API requests and new desktop connections must be rejected.
4. Expired/missing login: the API rejects it; the portal offers a sign-in-again link when it receives an auth error or Access redirect. Active lab deadlines continue. Browser/CORS failures may still need a manual top-level refresh.
5. Confirm normal typing/mouse input, inactivity warning, termination and feedback through the public hostname. Test fullscreen and WebSocket reconnect.
6. Revoke a membership and verify subsequent API/desktop authorization checks deny it.

## Membership changes

```bash
# Disable access to this classroom.
docker compose exec api python classrooms.py member-disable pccoer-linux --email student@example.com
# Re-enable it using the same enrollment command.
docker compose exec api python classrooms.py member-add pccoer-linux --email student@example.com
```

Revocation takes effect at the next request/connection authorization check. It does not forcibly close an already-established WebSocket or delete the container immediately. Absolute expiry/cleanup still runs. A later operator dashboard should provide explicit terminate/revoke controls. Disabling the college/classroom blocks new admissions; it does not replace membership revocation for existing labs.

## Operational limits and rollback

- Keep one API worker. The backend requires outbound HTTPS to the configured team's signing-key endpoint and an accurate host clock. Key-fetch failures reject access rather than bypass validation.
- Sessions store verified subject and email alongside classroom identity. Treat database backups as private. Changing identity-provider/Cloudflare identity mappings can prevent a user from resuming an old session.
- Switching `AUTH_MODE=off` does not expose already user-bound sessions: those remain inaccessible without a verified actor. Drain user-bound sessions before switching modes. Restore a prior complete source/config backup only after sessions end; schema additions can remain.
- The browser still uses generated desktop credentials. This does not remove the desktop Basic Auth prompt.
- Identity enforcement is an opt-in pilot feature, not a complete enterprise tenancy boundary: container networking/kernel isolation, quotas, rate limits, admin roles and the dashboard remain future work.
- Automated checks use local RSA keys and mocked Docker; real Cloudflare, Nginx streaming and Pi deployment still need the acceptance steps above.

## Administrator bootstrap

Set `ADMIN_EMAILS=first@example.com,second@example.com` in the private backend `.env`
and recreate the API with `docker compose up -d --force-recreate api`.
Both accounts must also be allowed by the Cloudflare Access application policy.
Do not commit real administrator email lists to the public repository.

`GET /api/me` includes `is_admin`. `GET /api/admin/me` returns the verified
administrator email and role; non-admin accounts receive 403. Admin access is
always disabled when `AUTH_MODE=off` or the allowlist is empty. Email headers
alone do not grant access. Removing an email and recreating the API revokes
admin authorization on subsequent requests.

This is the authorization foundation; a management dashboard is not implemented
yet. Admin status does not bypass classroom enrollment or session ownership.
