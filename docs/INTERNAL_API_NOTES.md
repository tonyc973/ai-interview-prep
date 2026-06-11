# Internal API Notes — verified against installed packages

> Verified on 2026-06-10 against the **actually installed** versions. Do not
> trust memorized signatures; these were read from source / introspection.
> Pins: crewai 1.14.6, nicegui 3.13.0, openai 2.41.0, sqlalchemy 2.0.50,
> pydantic 2.12.5, pydantic-settings 2.10.1.

## CrewAI 1.14.6

CrewAI 1.x uses **native provider SDKs** (no litellm for OpenAI). The OpenAI
provider (`crewai/llms/providers/openai/completion.py`) calls the `openai` SDK
directly. We bypass it entirely with a custom `BaseLLM` subclass so that **all**
LLM traffic flows through our gateway.

- `from crewai import Agent, Task, Crew, Process, BaseLLM, LLM`
- `BaseLLM(BaseModel, ABC)`: required field `model: str`; optional `temperature`,
  `stop`, `additional_params`. The **only abstractmethod** is:
  ```python
  def call(self, messages: str | list[dict],
           tools=None, callbacks=None, available_functions=None,
           from_task=None, from_agent=None,
           response_model: type[BaseModel] | None = None) -> str | Any
  ```
  - When `response_model` is set, `call()` must return the **parsed BaseModel
    instance** (CrewAI sets it as `task.output.pydantic`). Otherwise return `str`.
  - Helpers available: `self._format_messages(messages)` -> `list[{"role","content"}]`.
  - `model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)`.
    A subclass can declare extra fields (e.g. an injected ledger) — declare them as
    real model fields with `arbitrary_types_allowed`.
- `Agent(role=, goal=, backstory=, llm=<BaseLLM instance>, tools=[], verbose=,
  allow_delegation=False, max_iter=)`. Passing a `BaseLLM` instance to `llm=` works.
- `Task(description=, expected_output=, agent=, output_pydantic=<Model>, context=[...])`.
  Setting `output_pydantic` makes CrewAI pass `response_model=<Model>` to `llm.call()`.
- `Crew(agents=[...], tasks=[...], process=Process.sequential, verbose=)`.
  - `Process.sequential` / `Process.hierarchical`.
  - `crew.kickoff(inputs: dict) -> CrewOutput`; also `await crew.kickoff_async(inputs)`.
  - `CrewOutput.tasks_output[i].pydantic` holds each task's parsed model;
    `CrewOutput.pydantic` holds the last task's model.
- **Our agents use NO tools** (reason from provided inputs only). So our
  `GatewayLLM.call()` ignores `tools`/`available_functions` and handles only a
  plain completion + optional structured parse — no tool loop needed.

## OpenAI SDK 2.41.0

- Single client owned only by the gateway: `OpenAI(api_key=...)` / `AsyncOpenAI(...)`.
- Plain text: `client.chat.completions.create(model=, messages=, temperature=)`.
- Structured (stable, non-beta): `client.chat.completions.parse(model=, messages=,
  response_format=<PydanticModel>)`; result `.choices[0].message.parsed` is the model
  instance (or `.refusal`). Async equivalent on `AsyncOpenAI`.
- Usage: `resp.usage.prompt_tokens`, `.completion_tokens`, `.total_tokens`,
  `.prompt_tokens_details.cached_tokens`, `.completion_tokens_details.reasoning_tokens`.
- Retryable exceptions: `RateLimitError`, `APITimeoutError`, `APIConnectionError`,
  `InternalServerError` (subclass of `APIStatusError`). Non-retryable: `BadRequestError`,
  `AuthenticationError`, `NotFoundError`, `PermissionDeniedError`.
- **Structured-output schema constraints**: every field must be required (avoid
  defaults), enums OK, nested models OK. Avoid numeric `Field(ge=/le=)` in the
  schema — enforce ranges with pydantic `field_validator` that runs *after* parse,
  and describe the range in the field `description` so the model complies.

## NiceGUI 3.13.0

- `from nicegui import ui, app, run`, `from nicegui import context`.
- `ui.run(storage_secret=..., host=, port=, title=, reload=False, show=False)`.
- `app.storage.user` — signed server-side per-user dict; **requires** `storage_secret`
  in `ui.run()` and the request-tracking middleware NiceGUI installs automatically.
  Only accessible inside a page/request context.
- `app.storage.browser['id']` — stable browser/session id (for throttling, rotation).
- `run.io_bound(fn, *args)` — run blocking work (crew kickoff) off the event loop.
- `ui.echart({...})` — ECharts; use `radar` series for the competency chart.
- `app.add_middleware(Starlette middleware)` — for auth gate.
- `app.on_startup(coro)` / `app.on_shutdown(coro)` — lifecycle (DB init, engine dispose).
- `ui.navigate.to(path)`, `@ui.page('/path')`, `ui.dark_mode()`.
- `ui.context.client` / `nicegui.context` for current client.

## SQLAlchemy 2.0.50 (async)

- `create_async_engine("sqlite+aiosqlite:///./data/app.db")`; `async_sessionmaker`.
- Portable types only: `String`, `Text`, `Integer`, `Float`, `Boolean`,
  `DateTime(timezone=True)`, `JSON`, `Uuid`. Enums stored as `String` (Python-side
  `StrEnum`), never native DB enums — keeps Postgres swap a config change.
- `Mapped[...]` + `mapped_column(...)`; `DeclarativeBase` with a constraint
  naming convention so Alembic autogenerate is deterministic.
