# Admin dashboard

Open `https://YOUR_LAB_HOST/admin` after deploying the latest backend, frontend,
and Nginx configuration. Keep the existing Cloudflare Access application covering
the entire hostname. Set `AUTH_MODE=cloudflare` and `ADMIN_EMAILS` in the private
backend `.env`, as described in [verified login](verified-login.md).

Platform admins can manage all colleges. College admins manage only their assigned
colleges. Both use `/admin`; the backend filters data and checks every mutation.

## Available operations

- Create colleges; enable or disable college admissions.
- Create classrooms with a custom code, existing template, duration and slot limit.
- Rotate classroom codes; enable or disable admissions.
- Add up to 500 student emails per batch; disable or re-enable individual enrollment.
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
header. No cross-origin CORS is enabled. No CSV file upload, pagination,
billing or college-specific admin permissions is provided in this version.

## Bulk enrollment

Select a classroom and paste email addresses in Enroll students. Separate them
with newlines, spaces, commas or semicolons. Do not include CSV headers or names.
The server validates the entire batch before saving in one transaction; an invalid
entry saves nothing. Addresses are lowercased and duplicates ignored. Existing
disabled memberships are re-enabled. The result reports all counts. Retry safely
if the connection fails: existing enabled memberships are counted as unchanged.
This does not add students to Cloudflare Access policies or send invitations.

## Admin activity

The dashboard shows the latest 100 admin events. SQLite retains older events
and the normal database backup includes them. Database changes and their events
commit together. Termination records requested and completed/failed events
separately because Docker operations cannot share the SQLite transaction. A
requested event without an outcome may mean the API stopped mid-operation.

Events record the verified administrator email, UTC timestamp, action and target.
Individual enrollment events include the student email; bulk events include counts.
Codes, passwords and request bodies are not logged. Existing historical actions
are not reconstructed. This tracks successful dashboard changes and termination
attempts, not CLI changes, denied requests, or automatic session expiry.

There is no dashboard delete/edit operation for events. This is a local operational
log, not a tamper-proof audit service: a server/database operator can modify it.

## College administrator permissions

Platform admins are the verified emails configured in `ADMIN_EMAILS`. Only they
can create/disable colleges and grant or revoke college-admin assignments.

In the College administrators panel, choose a college and enter the faculty email.
The same email may be assigned to multiple colleges. Assignments take effect on
subsequent API requests, without rebuilding or restarting the server. Revoking
one college assignment keeps any other assignments intact. An assignment does
not override platform privileges from `ADMIN_EMAILS`.

College admins can create classrooms in their assigned colleges, select from the
shared template catalog, rotate codes, manage enrollment, disable/enable classrooms,
terminate their colleges' labs, and read their colleges' feedback and activity.
They cannot grant roles, create/disable colleges, or access another college's labs.
Host capacity is shared. Per-college resource budgets and template entitlements
are not part of this release.

Allow faculty through the existing Cloudflare policy separately. Student lab
access still requires classroom enrollment; admin permission does not grant the
ability to open another student's desktop.

The schema upgrade is additive. Older activity events without a college scope
remain visible only to platform admins. Colleges cannot be reassigned or deleted
through this dashboard. CLI operations continue to require trusted host access.

### Deployment acceptance test

1. As a platform admin, grant a separate test/faculty email access to one college.
2. In a separate browser profile, sign in as that email and visit `/admin`.
3. Confirm that only the assigned college's classrooms, roster, labs, feedback
   and new activity appear. Test a classroom/enrollment change in that college.
4. As platform admin, revoke the assignment. Refresh the faculty dashboard;
   it should deny access unless that email has another college assignment.

Automated API tests cover attempts to manipulate another college by changing IDs,
plus role escalation, revocation, scoped reads and session termination. Live
Cloudflare/browser verification is still required on your deployment.

## Student storage subscriptions

Use **Student storage subscriptions** to select a classroom, paste enrolled emails,
and assign Temporary or Persistent storage with an optional expiry date. Dates in
the form use your browser's local timezone and are stored as UTC. Leaving expiry
blank grants persistence until manually changed. This is manual entitlement
management, not payment integration. Existing sessions keep their mounts; changes
apply to the next session. No saved data is deleted on expiry or disable.

The server must allow the template through PERSISTENT_HOME_TEMPLATES before granting
persistence. Existing pilot users need explicit assignment after this update; their
saved volumes are retained. Persistent hard disk quotas are still pending and the
dashboard labels this limitation. See [student storage](student-storage.md).
