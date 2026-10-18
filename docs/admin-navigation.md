# Admin navigation and initial system checks

The dashboard now opens on Overview. Use the menu to switch between Classrooms,
Students, Storage, Active Labs, Feedback and Activity without scrolling through
all forms. On small screens use the Menu button. The selected section is stored
in the URL fragment, so refresh and browser Back/Forward preserve navigation.
Unsubmitted form values stay in place when switching sections.

Platform admins additionally see Colleges, Administrators and System Health.
College admins continue to receive only their permitted college data. Menus do
not replace backend authorization. The new system-health endpoint requires a
platform admin before inspecting any services.

System Health refreshes every 60 seconds while its page is visible: Docker response, proxy container state,
quota broker health, network guard validation, and free space on the filesystem
holding SESSION_DB. Click Check system health to refresh. A running proxy does
not establish that Cloudflare or the public desktop works. A failed service
check is shown as UNAVAILABLE, not healthy. Internal exception text is withheld.

Disk space is WARNING below 5 GiB or 10% free, CRITICAL below 2 GiB or 5% free.
This filesystem is normally the Pi SD card, but can differ on other deployments.
No files are deleted. Critical space and unavailable disk checks now block new labs; see [disk protection](disk-protection.md).
Saved-home project quotas do not constrain other container writable paths.
External alerts, host memory monitoring and hard whole-desktop disk
limits remain separate work; this is not completion of those milestones.

## Deploy

End active labs before running the existing classroom installer. This release
changes the API and admin page; it does not require reinstalling storage or
network isolation.

```bash
cd ~/linux-lab-classrooms-update
git fetch origin
git checkout main
git pull --ff-only origin main
bash scripts/install-classrooms.sh "$HOME/linux-lab/backend"
```

Reload /admin (hard refresh if the old page remains). Check:

- Platform admin: all menu entries appear, Overview opens, and each form/table
  appears under its section. Switching sections retains unsubmitted input.
- College admin: Colleges, Administrators and System Health are absent; existing
  college-scoped operations still work. A direct system-health request is 403.
- Narrow window: Menu opens/closes, sections and tables remain usable.
- System Health: click the check button and confirm current service results.
  Review any disk warning before producing additional local backup copies.

Do not prune saved-home volumes or remove backups to resolve warnings without
first identifying their purpose and verifying a usable off-device backup.
