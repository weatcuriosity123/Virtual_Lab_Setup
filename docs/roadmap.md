# Paid college pilot roadmap

## Working foundation

Single-host container desktops, verified Cloudflare login, owner-bound session
access and resume, custom classroom codes, quotas, timers, idle termination,
feedback, platform admin dashboard, bulk enrollment, admin activity history.

## Six milestones

1. **College-specific permissions: implemented and API-tested.** Deploy and
   complete the two-account acceptance test in [admin.md](admin.md).
2. **Lab template readiness: in validation.** Build reproducible branch-specific images,
   verify required tools/versions and hardware requirements, and test practicals.
   Existing Linux template remains the starting point. ROS2/Gazebo is not yet
   provided as a tested branch image.
3. **Student work storage: pilot implementation.** Opt-in verified student homes
   and manual per-student subscription/expiry controls are implemented; see [student-storage.md](student-storage.md). Live expiry and
   isolation validation remain required. Hard-quota pool integration is implemented
   with local tests; the Pi deployment, in-container hard quota and saved-file
   recovery after reboot passed on 2026-10-18. Cold backup and isolated recovery
   drill passed on the Pi; a Windows off-device archive was checksum-verified.
   Full replacement-host recovery and recurring backup operations remain pending. See [backup-recovery.md](backup-recovery.md).
4. **Reliability and isolation: in progress.** Startup session reconciliation is
   implemented and locally tested; API restart, active-session host reboot,
   capacity cleanup and saved-file recovery passed on the Pi on 2026-10-18.
   See [restart acceptance](restart-recovery.md).
   Runtime reconciliation, network isolation, monitoring and whole-host recovery
   remain pending.
5. **Capacity validation: pending.** Measure concurrent desktop workloads and
   establish supported student counts for each server and template.
6. **Pilot acceptance and launch: pending.** Run a real college practical, resolve
   findings, document onboarding/support, and establish pricing/operating costs.

The phase ends with a controlled paid college pilot, not merely completion of
UI features. Automatic multi-server scaling and billing are a later expansion.
No reliable overall completion percentage is claimed: image compatibility,
capacity and real-classroom validation still require measured evidence.
