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

College admins can view only their assigned colleges, rotate codes, disable enrollment
or classroom admissions, terminate their colleges' labs, and read feedback/activity.
New classrooms, new/re-enabled enrollments, classroom re-enabling, and any storage
subscription changes require platform-admin approval. These restrictions are enforced
by the API, including when callers bypass the dashboard. Saved-home deletion is
platform-only. College admins cannot grant roles or modify colleges or template resources.
Host capacity remains shared. This approval gate prevents unapproved changes to access;
it is not a cloud billing cap or a limit on repeat usage by already-approved students.

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
saved volumes are retained. The quota backend enforces per-student MiB allowances after host installation;
legacy mode remains unlimited and is labeled accordingly. See [student storage](student-storage.md).

## Permanently deleting a saved home

Open **Saved student homes** and use **Delete permanently** for the correct student,
classroom and template. End attached labs first, including any stopped containers
that still reference the volume. Type `DELETE student@email` exactly as prompted.
The action is scoped to your colleges and audited. It removes the selected saved
files and settings, leaves other homes/backups alone, and does not cancel the storage
subscription. No undo is provided; a future persistent session starts a fresh home.

### Storage allowance

The storage form accepts 64–16384 MiB (default 1024). The allowance applies on the
next persistent lab start. The host quota pool must first be installed using
`scripts/install-quota-storage.sh`; the API refuses to silently substitute temporary
storage when it is unavailable. Saved-home rows show actual quota usage and the
current enforced limit. Subscription rows show the requested next-start allowance.
Pool capacity and current home usage may prevent a requested allowance being applied.
Original migration copies are retained separately from the active quota home.


## Storage expiry and approval requests

Storage now lists every enrolled email, next-lab access, allowance, and expiry.
A persistent entitlement with NULL expiry displays **Not set yet — no expiry** and
continues indefinitely. Temporary access displays **Not applicable**. Existing data
is not reinterpreted or assigned a default expiry during migration.

Platform admins select **Edit access / expiry**, set a future local date/time or
leave it blank, and save. Changes apply to the next lab. Expiring or disabling
persistence does not delete retained homes or stop existing sessions.

College admins use **Request persistent storage**; they cannot apply changes or
permanently delete saved files. Classroom creation/enrollment forms submit requests
for college admins. Enabling a disabled classroom or enrollment also submits a request.
The **Approvals** menu shows pending and reviewed requests. Only platform admins can
approve/reject. Classroom approval requires the platform admin to set a class code;
share it privately after approval. Codes are never stored in request payloads or logs.

Requests are scoped to their college, include a reason, and record requester/reviewer
and timestamps. Identical pending requests reuse the existing ID; each college can
have at most 100 pending requests. Approval, access change and audit commit in one
SQLite transaction. Repeated/concurrent reviews cannot apply a request twice.
If affected access or resource configuration changed in the meantime, approval fails;
reject the stale request and submit a fresh one. Expiries are revalidated on approval.
No request sends email or provisions cloud infrastructure. Review the dashboard queue.

Existing approved access continues after upgrading. Audit existing indefinite
entitlements before any cloud deployment. Enforced monetary budgets, aggregate
persistent-byte budgets, scheduled access and monthly student-hour quotas are separate
future controls; this feature does not promise a zero-overrun cloud bill.

### Deploy this update

Back up the live database and backend first. Install the reviewed branch with the
existing installer. API startup creates `admin_requests` and its index without
changing existing entitlements or runtime RAM/task limits. A code rollback may leave
this additive table in place, but restores the older, broader college-admin permissions.
For acceptance: sign in as each role, submit a storage request, verify no entitlement
changed, approve as platform admin, verify the expiry/allowance, then test rejection
and attempted direct college-admin storage writes (403).


## College Plans & Usage

The Plans & Usage menu shows each assigned college's seat limit, active reservations,
monthly used/reserved hours, reserved persistent allowance and approved templates/hours.
Only portal admins save plans. College admins submit a `college_plan` approval request;
approval applies the complete proposed plan atomically. Requests cannot self-approve or
access another college. Changing a plan requires that the college has no running or
starting labs and no outstanding admission reservation. It cannot lower caps below
already-consumed monthly hours or reserved storage. Timezone is fixed after first save
so changing it cannot reset the monthly allowance.

Existing colleges are **Not configured** after deployment. They retain their previous
behavior until a portal admin explicitly saves a plan. New colleges likewise require
explicit plan configuration before being considered budget-controlled. No RAM, CPU,
task, image or global host-capacity configuration changes automatically.

### Admission and time accounting

* College-wide seats apply across all classrooms, in addition to classroom and host caps.
* Only allowlisted template IDs can start. Template resources remain server-managed.
* Access uses an IANA timezone and selected weekdays (Monday=0), with one same-day window.
  Overnight windows and exceptions for holidays are not supported in this version.
* Each start reserves the classroom duration plus at most five startup minutes, clipped
  to closing time and the local calendar-month boundary. If insufficient monthly hours
  remain for that reservation, admission is refused before a desktop is created.
* Fewer than five minutes before closing cannot admit a new lab. On activation, the
  ordinary classroom timer is clipped to the reserved absolute deadline. The existing
  expiry/authorization checks and cleanup worker enforce that deadline.
* Used time includes startup and elapsed session time; reserved time includes used time
  plus the maximum remaining time of outstanding starts/labs. Activation releases unused
  startup reservation. Successful cleanup on early end releases unused future minutes.
  A failed launch with successful cleanup consumes no allowance. If cleanup fails or the
  API crashes, keep the reservation conservatively until its deadline; this is not
  provider billing telemetry and should not be billed as exact student attendance.
* Idempotent launch retries do not reserve again. SQLite IMMEDIATE transactions serialize
  college admission checks and reservations. The deployment remains a single Docker host
  and one API worker; global locks/routing/storage are not multi-host orchestration.
* Metering begins with planned admissions after configuration; historical sessions before
  configuration are not retroactively charged. A running lab cannot carry into the next
  college-local calendar month under a previous month's reservation.

### Persistent allowance accounting

The storage cap bounds **reserved subscription allowances**, not all physical cloud disk
bytes. Reservations use the highest assigned MiB per classroom/email and are seeded from
existing entitlement records on migration. Expired/disabled entitlements and quota
reductions do not reclaim a reservation automatically, since saved files/backups may
remain. New grants and increases must fit the college cap, including platform-admin
writes and approval actions. Saved-home admission rechecks the reservation to catch
operator/CLI changes and requires the quota backend for plan-managed persistence.

A student enrolled in two classrooms consumes two allowances. Images, logs, root disks,
legacy files, backups and identity-migration copies are not included in this allowance
meter. This is not a physical disk cap or monetary budget. Reservation reclamation after
verified deletion is deliberately not exposed yet; review retained files and raise the
approved pool when needed. Disk monitoring and cloud billing alerts remain necessary.

### Deployment acceptance

1. Install while student labs are stopped; the installer backs up sources/database and
   includes `plans.py`. The image installs timezone data for calendar rules.
2. Before saving, review each college's displayed existing storage reservation. Keep the
   Pi plan at one seat; choose real monthly hours and weekdays/window for the pilot.
3. As a college admin, verify view-only plan access and request an increase. As portal
   admin, inspect the exact values, approve or reject, and check the audit trail.
4. Verify a disallowed template or closed-hours start is refused; verify approved access
   works and used/reserved counters update on start/end. Do not increase Pi capacity to
   test a second heavy desktop.

All additions are database tables. Older code can ignore them on rollback, but doing so
also removes plan enforcement. Keep the single API worker and review approvals before
changing capacity during EC2 migration.
