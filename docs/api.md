# API overview

Public requests use `/api`; FastAPI paths below omit that gateway prefix. Interactive docs are at `/api/docs`.

| Method/path | Authentication | Purpose |
|---|---|---|
| GET `/health` | None | Process health |
| GET `/sessions` | None | Occupied capacity and available slots |
| POST `/sessions` | JSON `access_code` | Start desktop; optional 32-hex `request_id` deduplicates retries |
| GET `/lab/{token}` | `X-Session-Password` | Status, expiry, server time and remaining seconds |
| GET `/lab/{token}/ready` | Same header | Authenticated desktop HTTP readiness |
| POST `/lab/{token}/activate` | Same header | Activate starting session; active-session expiry unchanged |
| GET `/lab/{token}/activity` | Same header | Idle warning/countdown and end reason |
| POST `/lab/{token}/activity` | Same header | Record activity after checking existing idle deadline |
| POST `/lab/{token}/terminate` | Same header | End session and remove desktop |
| POST `/lab/{token}/feedback` | Same header | Save/update feedback after session ends |
| DELETE `/sessions/{token}` | `access_code` query parameter | Legacy class-code termination |

Feedback JSON: `rating` integer 1–5, `worked` one of `yes`, `partially`, `no`, and `comments` up to 2000 characters. Session tokens are 32 lowercase hexadecimal characters. API credentials and desktop HTTP Basic authentication are separate request mechanisms using the same generated session password.

Expected errors include 401 invalid class code, 403 invalid session credentials, 409 invalid lifecycle transition, 429 all slots occupied, 503 service/cleanup not ready, and 422 invalid input. Creation failures return 500; inspect private server logs for the cause.

`starting` sessions count toward capacity but return zero remaining usage seconds until activation. The starting expiry is a five-minute preparation deadline. Active expiry is the configured usage deadline. Client-reported readiness is not an anti-abuse guarantee: the backend only independently verifies the desktop HTTP service.
