# CLAUDE.md

AI Interview Preparation Platform — CrewAI multi-agent pipeline + OpenAI API + NiceGUI frontend. Production-grade: every change must pass the quality gates below before being considered done.

## Commands

```bash
make install        # uv sync (locked deps only — never pip install ad hoc)
make dev            # run app locally (loads .env)
make lint           # ruff check + ruff format --check
make typecheck      # mypy --strict
make test           # pytest (unit + integration, LLM gateway always mocked)
make coverage       # pytest --cov, fails under 85% on services/ agents/ db/
make migrate m="…"  # alembic revision --autogenerate
make upgrade        # alembic upgrade head
make smoke          # ONE real OpenAI smoke run — opt-in only, never in CI
```

Definition of done for ANY change: `make lint typecheck test` all green. No exceptions, no `# type: ignore` without a comment justifying it.

## Stack (pinned — do not substitute or upgrade without explicit instruction)

- Python 3.12, managed with `uv` (pyproject.toml + uv.lock)
- CrewAI for agent orchestration; OpenAI SDK as the only LLM provider
- NiceGUI for ALL frontend including auth — no FastAPI routes for UI, no React
- SQLAlchemy 2.x async + SQLite (must remain Postgres-swappable: no SQLite-specific SQL)
- Pydantic v2 + pydantic-settings; structlog (JSON); pytest + pytest-asyncio; Alembic

Verify CrewAI and NiceGUI APIs against the installed package version before writing code that touches them. Both break APIs frequently — do not trust memorized signatures.

## Architecture invariants

```
app/config.py   app/main.py
app/domain/     pure models, no IO
app/db/         SQLAlchemy models, repositories, Alembic
app/services/   business logic
app/agents/     CrewAI agents, tasks, crews, output schemas, llm gateway
app/ui/         NiceGUI pages/components ONLY — zero business logic
app/middleware/ auth middleware
```

- Strict layering: ui → services → (db repositories | agents). Never skip a layer. UI never touches the DB or CrewAI directly.
- **All LLM traffic goes through the gateway module** (`app/agents/gateway.py`). Never import or call `openai` anywhere else. The gateway owns retries (tenacity, exponential backoff + jitter), timeouts, per-call token/cost accounting persisted to `UsageRecord`, and per-user/per-session cost caps.
- All agent outputs are validated Pydantic models (`ResearchBrief`, `QuestionBank`, `InterviewTurn`, `EvaluationReport`). Never parse free text with regex.
- The mock interview is a stateful turn loop managed in the service layer — one interviewer invocation per turn. Do NOT refactor it into a single `crew.kickoff()`.
- Long-running crew work runs via `run.io_bound`/background tasks — never block the NiceGUI event loop.
- User-provided JD/CV text is untrusted: always delimited, always treated as data, never interpolated as instructions.

## Security invariants

- Passwords: argon2id only. Never log passwords, hashes, or raw prompts at INFO (prompts at DEBUG only).
- Auth errors are generic ("invalid credentials") — never reveal whether an email exists.
- Session identity rotates on login; logout invalidates the session. Login throttling state is persisted, not in-memory.
- All config from env via pydantic-settings. App fails fast listing missing vars. `.env` is gitignored; update `.env.example` whenever adding a variable. Never hardcode secrets, keys, or model names outside config.

## Testing rules

- Tests NEVER hit the OpenAI API. Mock the gateway with deterministic fakes; assert against the Pydantic output schemas.
- Every bugfix gets a regression test. Auth changes require updating the auth unit suite (hashing, lockout, rotation).
- Schema changes require an Alembic migration in the same change — never edit models without one.

## Conventions

- Boring, explicit code over cleverness. Full type annotations everywhere (mypy --strict is the arbiter).
- structlog with session/request correlation IDs; no `print`, no f-string logging of user content.
- Ambiguity is resolved toward the stricter/more secure option, and the decision is recorded in `ARCHITECTURE.md` under "Decisions".
- Docs that must stay current with code: `README.md` (env var table), `ARCHITECTURE.md`, `SECURITY.md`.
