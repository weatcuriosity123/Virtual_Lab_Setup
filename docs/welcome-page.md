# Branded welcome and sign-in

Deploy the standard update script to install `/welcome`. It is a static public-facing
page with no account/session data and no API calls. Its sign-in buttons lead to
`/` and `/admin`, still protected by the existing Cloudflare Access application.

## Show the welcome page before authentication

Keep the existing whole-host Access application and its policies intact. Add a
separate self-hosted Access application for `vm.curiosity4u.in/welcome` only:

- Hostname: `vm.curiosity4u.in`
- Path: `welcome` (no wildcard)
- Policy action: Bypass
- Include: Everyone

Share `https://vm.curiosity4u.in/welcome` as the entry URL. More-specific Access
application paths take precedence. The bypass makes only this static welcome
path public; do not add a Bypass policy to the existing whole-host application.
Do not expose `/api`, `/s`, `/admin`, or `/` using a bypass. Do not change the
backend's configured Access audience to the welcome application's audience.

Cloudflare configuration is a manual deployment step; adding this file alone
cannot change the edge authentication screen. Test in a signed-out/incognito
browser: `/welcome` should load without login, and its sign-in links should
require authentication. Verify `/api/me` and an active desktop URL still require
login. Visiting the bare hostname still opens Cloudflare authentication.

## Improve the actual authentication screen

Cloudflare Zero Trust > Reusable components > Custom pages > Access login page
> Manage allows organization name, logo, header, footer and background color.
Suggested text: organization `Curiosity Lab`, header `Sign in to your classroom`,
footer `Use your enrolled college email. Contact your instructor for access.`
These settings affect all Access applications in the team. If using one identity
provider, evaluate instant authentication to skip the provider chooser. This
welcome page does not replace authentication or collect identity-provider passwords.

References:
- https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/
- https://developers.cloudflare.com/cloudflare-one/reusable-components/custom-pages/access-login-page/
