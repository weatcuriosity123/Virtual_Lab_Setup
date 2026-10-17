# Colleges, classrooms and lab templates

This release adds code-based admission for multiple classrooms. With the default AUTH_MODE=off, anyone holding a valid code can request a lab. Optional [verified login](verified-login.md) now adds signed-in identity, explicit classroom email rosters and owner-bound sessions. No college, template or real code is seeded automatically.

## Upgrade the working Pi

From a separate checkout of the updated repository, run:

```bash
bash scripts/install-classrooms.sh ~/linux-lab/backend
```

The installer requires no active/starting sessions. It backs up the source files and SQLite using the existing API, copies the updated Python modules, Dockerfile and portal, updates the matching identity module and Nginx configuration, rebuilds the API and restarts Nginx. It preserves `.env` and Compose; generated routes are refreshed at API startup. Database migration is additive and repeatable. It does not install a new student image.

## Create PCCOER and a Linux lab

Run these commands from the working backend after upgrading:

```bash
cd ~/linux-lab/backend
docker compose exec api python classrooms.py college-add pccoer --name "PCCOER"
docker compose exec api python classrooms.py template-add linux-basic-v1 --name "Linux Basics v1" --image linux-lab:1.0
docker compose exec api python classrooms.py classroom-add pccoer-linux --college pccoer --template linux-basic-v1 --name "Linux Practice" --minutes 60 --slots 2
```

The last command privately prompts for the code twice. You can choose `PCCOER` (six characters), but use a less predictable code for a shared pilot. Codes are case-sensitive, 6–200 characters, and cannot have surrounding spaces. Do not pass real codes as command arguments, commit them or share them in chat.

Students use the same portal and enter the assigned code. The header displays the college/classroom. New sessions use the classroom's template, duration and capacity; existing sessions retain the duration and labels recorded at creation.

## Add a second classroom or template

To test two classrooms with the known working image:

```bash
docker compose exec api python classrooms.py template-add linux-practice-v1 --name "Linux Practice v1" --image linux-lab:1.0
docker compose exec api python classrooms.py classroom-add pccoer-practice --college pccoer --template linux-practice-v1 --name "Practice Batch" --minutes 45 --slots 2
```

Enter a different code at the prompt. These are two catalog templates using the same tested image, not different installed toolsets.

For robotics, first build and validate the ROS/Gazebo image on suitable hardware. Then register a versioned template with its real local image tag and measured resource needs. Template flags are `--memory-mb`, `--cpu-millis` (1000 = one CPU), `--shm-mb`, `--home-mb` and `--pids`. Defaults match the original Linux lab. Registration does not build, pull or verify the image; session creation checks that it exists. Create a new template ID for each image version.

A classroom can expire: supply `--expires-at '2026-12-31T23:59:00+05:30'` at creation, using your own future timezone-aware timestamp. Expiry blocks new admissions and does not terminate already admitted labs.

## Operator commands

```bash
# Inspect configuration; codes/hashes are not printed.
docker compose exec api python classrooms.py list
# Privately choose a replacement code.
docker compose exec api python classrooms.py code-rotate pccoer-linux
# Block new admissions to a classroom.
docker compose exec api python classrooms.py set-enabled classroom pccoer-linux no
# Enable it again.
docker compose exec api python classrooms.py set-enabled classroom pccoer-linux yes
# Block new admissions to all classrooms of a college.
docker compose exec api python classrooms.py set-enabled college pccoer no
# Block admissions using an image template.
docker compose exec api python classrooms.py set-enabled template linux-basic-v1 no
```

Changes apply to subsequent admission checks; a creation already in progress may complete. Disable/rotate does not revoke running desktops or resume passwords. Existing labs still end through their normal expiry/termination controls. There is no public admin API in this release. Commands require operator access to the Docker host. Duplicate IDs and duplicate codes (including disabled classrooms) are rejected.

## Legacy code and capacity

The existing `CLASS_ACCESS_CODE` remains accepted by default and uses the old image/duration settings. To require classroom codes only, add `ALLOW_LEGACY_CLASS_CODE=false` to `.env`, then recreate the API and restart the proxy during maintenance. Old session passwords still resume existing sessions. A classroom code cannot equal the configured legacy code when created/rotated.

`MAX_SESSIONS` remains the host-wide limit. A classroom's `--slots` is an additional cap, not a reservation: other classrooms can consume the host's available capacity. Starting sessions count toward both caps. `/api/sessions` reports global capacity; the classroom is identified only after code submission. There is no aggregate college quota or CPU/RAM scheduler yet.

Codes are stored as salted PBKDF2 hashes, not plaintext. This small-pilot implementation checks catalog hashes on admission; large catalogs require a different enrollment/lookup design and rate limiting. Keep the single API worker. The database remains sensitive because session passwords are still stored there.

Legacy DELETE /sessions/{token} is now restricted to the code's own classroom (the old global code only applies to legacy sessions). Use the portal's session-password termination endpoint instead of putting codes in URLs.

## Validation

Tests cover migration from the old schema, legacy compatibility, code rotation/disable/expiry, template resource selection, classroom/global capacity, retry isolation, scoped legacy deletion and fixed per-session duration. Tests use dummy images and mocked Docker, not a live robotics desktop. Run the live acceptance checks after deployment.
