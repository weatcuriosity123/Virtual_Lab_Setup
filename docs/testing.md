# Validation

Run from the repository root with Python 3.12 and Node.js available (Node is only needed for JavaScript syntax checking, not deployment):

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install fastapi docker httpx "PyJWT[crypto]>=2.10,<3"
bash scripts/check.sh
```

The tests use temporary SQLite files and mock Docker/readiness calls. No Docker containers are launched and no real class code is needed. They check lifecycle transitions, capacity, retry deduplication, authentication, activation, unchanged resume expiry, inactivity and feedback. They are not end-to-end desktop tests.

## Live acceptance

1. Check `/api/health` and create a lab from the root portal.
2. Confirm loading thoughts rotate, credentials remain available and a desktop eventually appears.
3. Confirm usage time starts after activation; retry/refresh must not create duplicate desktops or reset an active deadline.
4. Test keyboard and mouse interaction inside the desktop, then leave it idle: warning at roughly three minutes, termination at roughly four, feedback follows. Polling adds some delay.
5. Test manual End Lab while starting and while active; verify slot release and container/route removal.
6. Disconnect/reconnect and resume by ID/password before expiry. Active deadlines keep running offline.
7. Verify invalid credentials and full-capacity rejection. Abandon a new startup and confirm cleanup after its five-minute deadline.
8. Test package-installation exemption with the actual image; verify the absolute session deadline still applies.
9. Check a host reboot/maintenance procedure explicitly; automatic session reconstruction is not currently provided.

Do these on a test host/hostname before changing the student image or migrating to EC2. See the scaling guide for load testing; HTTP throughput alone does not establish desktop capacity.

Classroom regression checks also cover migration, per-classroom admission, resources, code rotation/expiry and cross-classroom retry/termination isolation. See [classrooms](classrooms.md).

Identity tests verify real RSA signatures using a local test key and exercise HTTP routes for expired/forged tokens, wrong issuer/audience, membership, owner isolation and desktop authorization. Cloudflare/JWKS network and real Nginx streaming are not simulated end-to-end.
