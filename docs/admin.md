# Admin dashboard

Open `https://YOUR_LAB_HOST/admin` after deploying the latest backend, frontend,
and Nginx configuration. Keep the existing Cloudflare Access application covering
the entire hostname. Set `AUTH_MODE=cloudflare` and `ADMIN_EMAILS` in the private
backend `.env`, as described in [verified login](verified-login.md).

Platform admins can manage all colleges. This release does not implement
college-scoped instructor roles.

## Available operations

- Create colleges; enable or disable college admissions.
- Create classrooms with a custom code, existing template, duration and slot limit.
- Rotate classroom codes; enable or disable admissions.
- Add, disable or re-enable student email enrollment.
- List active/starting labs and terminate them after confirmation.
- Read the latest 100 feedback submissions.

Codes are hashed and cannot be retrieved. Record the chosen code privately before
submitting; rotate it if lost. No desktop passwords or code hashes are returned
by the dashboard APIs. The global host capacity still caps concurrent sessions.
Disabling admissions does not end existing labs. Disabling enrollment applies on
subsequent access checks, but does not forcibly close established WebSockets.
Use Terminate to remove a lab immediately; temporary work is deleted.

Templates are selected from the server catalog. Install images and configure
resource limits with the existing CLI; the browser cannot upload or pull images.
The existing Cloudflare policy must also admit enrolled emails. Dashboard roster
changes do not edit Cloudflare policies.

## Deployment and verification

End active labs, update the source checkout and run
`scripts/install-classrooms.sh ~/linux-lab/backend`. This backs up source and
SQLite, installs `admin.py` and `admin.html`, rebuilds the API, and restarts Nginx.
The `/admin` static page contains no private data; every management API requires
verified admin authorization. Students who open the page see an access error.

Test with an admin and a non-admin account. Create a test college/classroom,
enroll a student, launch a lab through the student portal, and confirm that it
appears in Active labs. Terminate that test lab and verify feedback still works.
Use Refresh to reload lists; there is no automatic refresh in this release.

The dashboard uses same-origin JSON requests and a required custom mutation
header. No cross-origin CORS is enabled. No audit log, bulk import, pagination,
billing or college-specific admin permissions is provided in this version.
