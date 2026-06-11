"""Dashboard: list prep sessions and create new ones."""

from __future__ import annotations

from typing import Any

from nicegui import background_tasks, ui

from app.container import get_container
from app.domain.enums import InterviewStatus, SeniorityLevel, SessionStatus
from app.middleware.auth import current_user_email
from app.services.session_service import SessionInputError
from app.ui import theme
from app.ui.util import notify_error, require_user_id

_STATUS_COLOR = {
    SessionStatus.PENDING: "grey",
    SessionStatus.RESEARCHING: "blue",
    SessionStatus.GENERATING: "blue",
    SessionStatus.READY: "green",
    SessionStatus.FAILED: "red",
}


@ui.page("/")
async def dashboard_page() -> None:
    user_id = require_user_id()
    if user_id is None:
        return
    container = get_container()
    sessions = await container.sessions.list_sessions(user_id)
    name = (current_user_email() or "there").split("@")[0]

    with theme.frame(""):
        # Hero
        with ui.row().classes("glass p-6 items-center justify-between w-full fade-up"):
            with ui.column().classes("gap-1"):
                ui.label("Your interview prep").classes("pill pill-primary w-fit")
                ui.label(f"Welcome back, {name}.").classes("display text-3xl font-extrabold")
                ui.label(
                    "Spin up a session and let the agents research, quiz, and grade you."
                ).classes("ink-muted")
            ui.button("New session", icon="add", on_click=_open_new_session_dialog).classes(
                "cta"
            ).props("unelevated")

        if not sessions:
            with ui.column().classes("glass p-10 items-center gap-3 w-full fade-up d1"):
                ui.icon("auto_awesome", size="44px").classes("text-[color:var(--teal)] float")
                ui.label("No sessions yet").classes("display text-xl font-bold")
                ui.label("Create your first prep session to get started.").classes("ink-muted")
                ui.button("New session", icon="add", on_click=_open_new_session_dialog).classes(
                    "cta"
                ).props("unelevated")
            return

        ui.label(f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}").classes(
            "ink-muted text-sm"
        )
        with ui.column().classes("w-full gap-3"):
            for i, prep in enumerate(sessions):
                delay = f"d{min(i + 1, 4)}"
                with (
                    ui.row()
                    .classes(
                        f"glass lift p-5 items-center justify-between w-full fade-up {delay} "
                        "cursor-pointer"
                    )
                    .on("click", lambda p=prep: ui.navigate.to(f"/session/{p.id}"))
                ):
                    with ui.row().classes("items-center gap-4"):
                        ui.element("div").classes("brand-dot").style("opacity:.85")
                        with ui.column().classes("gap-1"):
                            ui.label(prep.target_role).classes("text-lg font-bold")
                            ui.label(f"{prep.target_company}  ·  {prep.seniority.label}").classes(
                                "ink-muted text-sm"
                            )
                    with ui.row().classes("items-center gap-3"):
                        if prep.interview_status == InterviewStatus.EVALUATED:
                            theme.status_badge("scored", "secondary")
                        theme.status_badge(
                            prep.status.value, _STATUS_COLOR.get(prep.status, "grey")
                        )
                        ui.icon("arrow_forward").classes("ink-muted")


def _open_new_session_dialog() -> None:
    container = get_container()
    with ui.dialog() as dialog, ui.card().classes("glass w-full max-w-xl p-6 gap-3"):
        ui.label("New interview prep session").classes("display text-xl font-bold")
        ui.label("Paste a real job posting for the best results.").classes("ink-muted text-sm")
        role = ui.input("Target role").props("autofocus outlined dense").classes("w-full")
        company = ui.input("Target company").props("outlined dense").classes("w-full")
        seniority = (
            ui.select(
                {level.value: level.label for level in SeniorityLevel},
                value=SeniorityLevel.MID.value,
                label="Seniority",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        jd = (
            ui.textarea("Job description (paste the posting)")
            .props("outlined rows=6 maxlength=20000")
            .classes("w-full")
        )
        cv = (
            ui.textarea("Your CV (optional, plain text)")
            .props("outlined rows=4 maxlength=20000")
            .classes("w-full")
        )

        async def _on_upload(e: Any) -> None:
            try:
                cv.value = await e.file.text()
                ui.notify("CV loaded.", type="positive")
            except Exception:
                notify_error("Could not read that file. Paste the text instead.")

        ui.upload(
            label="Or upload .txt / .md",
            auto_upload=True,
            max_file_size=1_000_000,
            on_upload=_on_upload,
        ).props('accept=".txt,.md" flat').classes("w-full")

        async def create() -> None:
            create_btn.props("loading")
            try:
                prep = await container.sessions.create_session(
                    user_id=require_user_id(),  # type: ignore[arg-type]
                    target_role=role.value or "",
                    target_company=company.value or "",
                    seniority=SeniorityLevel(seniority.value),
                    job_description=jd.value or "",
                    cv_text=cv.value or None,
                )
            except SessionInputError as exc:
                notify_error(exc.user_message)
                return
            finally:
                create_btn.props(remove="loading")
            background_tasks.create(container.sessions.run_pipeline(prep.id))
            dialog.close()
            ui.navigate.to(f"/session/{prep.id}")

        with ui.row().classes("w-full justify-end gap-2 mt-1"):
            ui.button("Cancel", on_click=dialog.close).props("flat color=white")
            create_btn = (
                ui.button("Create & run", on_click=create).classes("cta").props("unelevated")
            )
    dialog.open()
