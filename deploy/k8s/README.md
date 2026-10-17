# Standalone deployment — "Sign in with Shizuha ID" (PLAT-353)

notes deploys independently of the shizuha-stack monorepo. Auth = OIDC against
Shizuha ID (authz-code + PKCE, BFF; RS256 validated via JWKS).

## Env contract (backend)
| Var | Value |
|---|---|
| SHIZUHA_OAUTH_CLIENT_ID / SECRET | from k8s Secret `shizuha-notes-oauth` (client registered on ID) |
| SHIZUHA_OAUTH_ISSUER | ID base URL (token endpoint = `{issuer}/api/oauth/token`) |
| SHIZUHA_OAUTH_AUTHORIZE_URL | browser-facing consent page, e.g. `https://…/id/oauth/authorize` |
| SHIZUHA_OAUTH_JWKS_URL | `{issuer}/.well-known/jwks.json` |
| SHIZUHA_EXPECTED_ISSUER / SHIZUHA_SERVICE_NAME | iss check / aud=`notes` |
| NOTES_PUBLIC_URL / NOTES_FRONTEND_URL | public origin (callback) / SPA landing |
| SHIZUHA_AUD_ENFORCE=true | reject tokens not minted for notes |
| NOTES_DISABLE_HS256=1 | **final cutover only** — see below |

## HS256 grace (IMPORTANT)
Agents authenticate to the notes MCP with HS256 service tokens today. RS256-only
mode (`NOTES_DISABLE_HS256=1`) locks them out (verified live: 401). Keep the
grace (default) until agent M2M tokens migrate to OAuth client-credentials,
then flip the env var. Human sign-in is already fully OIDC either way.

## Frontend
Build with `/login` routed (standalone "Sign in with Shizuha ID" page);
`VITE_LOGIN_URL` reverts to `/id/login` for platform-integrated deployments.
