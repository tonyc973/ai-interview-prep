# Security

This documents the threat model and the concrete controls in the codebase. When
a requirement was ambiguous, the stricter interpretation was chosen.

## Authentication

- **Password hashing:** argon2id only (`argon2-cffi` defaults), via
  `app/services/security.py`. Passwords are never stored or logged in any form.
  Hashes are transparently upgraded (`check_needs_rehash`) on successful login.
- **No bcrypt 72-byte pitfall:** argon2 has no silent truncation; full passwords
  are hashed.
- **Generic errors / no user enumeration:** every login failure returns the same
  message, *"Invalid email or password."* An unknown email still runs an argon2
  verify against a precomputed dummy hash (`verify_dummy`) so response time does
  not reveal whether an account exists.
- **Password policy:** minimum length (default 12) **and** a zxcvbn strength
  score ≥ 3, with the email fed in as a `user_input` so email-derived passwords
  score poorly.
- **Throttling (persisted, not in-memory):** every attempt is written to
  `login_attempts`. Lockout is computed per **account** and per **IP**, with an
  **exponential** backoff (`base * 2^overage`, capped). State survives restarts.
  The lockout is checked *before* the password is verified, so a locked account
  cannot be brute-forced even with the correct password.
- **Sessions:** authentication state lives in NiceGUI's **signed**
  `app.storage.user` (HMAC via `APP_STORAGE_SECRET`, which the app refuses to
  start without). On login we **clear prior storage and mint a fresh session
  token** (`login_user`) to mitigate session fixation. Logout clears the session.

## CSRF / NiceGUI threat model

NiceGUI is **not** a traditional form-POST app: after the initial page load,
interactions happen over an authenticated WebSocket bound to the client/browser
session, and state mutations are Python event handlers — not cross-site-forgeable
form submissions. The classic CSRF vector (an attacker's page auto-submitting a
form to our cookie-authenticated endpoint) therefore does not map directly here.

Controls and residual risks:

- **Signed session storage.** `app.storage.user` is signed with
  `APP_STORAGE_SECRET`; a client cannot forge or tamper with auth state.
- **Auth gate middleware.** `AuthMiddleware` redirects unauthenticated requests
  to `/login` for everything except `/login`, `/register`, `/healthz`, and
  NiceGUI's own internal/static routes.
- **Open-redirect prevention.** `?redirect_to=` is only honored for same-site
  **relative** paths (`/...`, not `//...` or absolute URLs).
- **Deployment guidance.** Terminate TLS in front of the app; set
  `SameSite=Lax/Strict` and `Secure` on cookies at the proxy. WebSocket origin
  checking should be enforced at the proxy for hardened deployments — NiceGUI
  binds the socket to the signed session, but origin pinning is defense in depth.

## LLM / agent safety

- **Prompt-injection hygiene.** All user-provided text (job description, CV,
  candidate answers) is wrapped in explicit delimiters and the model is
  instructed to treat the contents as **untrusted data, never instructions**
  (`app/agents/prompts.py`). The system prompt carries a standing guard sentence.
- **Structured outputs only.** Agents return validated Pydantic models via the
  OpenAI structured-output API. No free-text-with-regex parsing.
- **Input limits.** Job description and CV are length-capped
  (`APP_MAX_JD_CHARS` / `APP_MAX_CV_CHARS`) with clear UI validation.
- **Cost caps as abuse mitigation.** The gateway enforces a hard per-session and
  per-user/day USD cap (seeded from persisted spend) *before* each call; exceeding
  it refuses the call rather than spending unboundedly.

## Secrets & logging

- All secrets come from the environment via pydantic-settings; the app fails fast
  with a readable, secret-free message listing missing/invalid variables.
- Secrets are wrapped in `SecretStr` so they never render in logs or tracebacks.
- `.env` is gitignored; only `.env.example` (placeholders) is committed.
- Structured logs (structlog/JSON) record model, latency, tokens, cost, and
  correlation ids — **never** prompt contents at INFO (DEBUG only, opt-in) and
  never passwords/hashes.

## Reporting

This is a reference/educational project. For real deployments, add: email
verification, password reset, rate-limiting at the proxy, audit logging, and a
managed Postgres with backups.
