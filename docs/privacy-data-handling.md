# Institutional privacy and data handling notices

The welcome page, student portal, and admin dashboard link to `/privacy-policy`
and `/data-handling`. Notices are self-contained HTML without scripts, external
fonts, tracking, account data, or API requests. Footer links open a separate tab
so the active student desktop is not replaced. The administrator footer is outside
the authenticated-content panel so the notices remain reachable on errors.

## Content scope

The notice describes the current implementation, including persistent-home
expiry versus deletion, retained backups, browser credentials, operational records,
and bounded student-requested packet captures. It does not claim institutional
approval, a particular legal compliance certification, a hosting region, a fixed
retention period, or guaranteed erasure. The contact route is the institution's
lab administrator/instructor; no personal email is published without designation.
Institutions should provide their named operator/privacy contact and their approved
retention and backup-disposal arrangements when available, and update this notice
when practices change. Publishing a notice does not implement deletion controls.

## Deployment

This change is based on deployed revision d4db97bff7b4cb6674690ff4dc030e6042852d75
from feature/pi-mixed-capacity. Use the standard installer after labs have ended:

```bash
cd ~/linux-lab-classrooms-update
git fetch origin feature/privacy-data-handling
git switch --detach origin/feature/privacy-data-handling
bash scripts/install-classrooms.sh "$HOME/linux-lab/backend"
```

The installer refuses active/starting sessions, creates source/database backups,
installs all HTML files plus the matching Nginx config, and checks service health.
Do not force past a dirty checkout or an active-session refusal.

## Public access before sign-in

Keep the whole-host Cloudflare Access application's protection intact. As with
`/welcome`, configure separate self-hosted Access applications for these two paths
on the existing lab hostname (`vm.curiosity4u.in` in project documentation):

- `privacy-policy` (no wildcard)
- `data-handling` (no wildcard)

For each path application use Bypass with Include Everyone. Never add Bypass to
the whole-host application or expose `/api/*`, `/s/*`, `/admin`, or `/`.
Do not change the backend Access audience. Repository deployment cannot configure
Cloudflare policies. More-specific path applications take precedence; see:
https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/
https://developers.cloudflare.com/cloudflare-one/access-controls/policies/common-policies/

## Acceptance

1. Locally verify `/privacy-policy` and `/data-handling` return HTTP 200 with the
   expected titles and no-store headers through port 8080.
2. In a signed-out browser, open both public HTTPS paths and follow the welcome
   footer links. Both notices should be readable without authentication.
3. Confirm `/`, `/admin`, `/api/me`, and a desktop `/s/.../` URL still require
   the original authentication and authorization.
4. In a signed-in student tab, open each footer link and verify the original
   tab/session remains open. Check keyboard focus and narrow-screen text wrapping.
5. Check the admin footer when content is loaded and when authorization fails.

Rollback: restore frontend files and nginx/default.conf from the installer backup,
remove the two new notice files if absent from that backup, then validate and reload
Nginx. Remove only the two new path-specific Cloudflare applications if rolling back
public access. Backend/database rollback is not needed for these notice changes.
