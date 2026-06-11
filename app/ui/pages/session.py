"""Session detail: pipeline progress, research brief, and question bank."""

from __future__ import annotations

import uuid
from typing import Any

from nicegui import ui

from app.agents.schemas import QuestionBank, ResearchBrief
from app.container import Container, get_container
from app.db.models import PrepSession
from app.domain.enums import InterviewStatus, SessionStatus
from app.ui import theme
from app.ui.util import notify_error, require_user_id

_PROGRESS_TEXT = {
    SessionStatus.PENDING: "Queued…",
    SessionStatus.RESEARCHING: "Researching the role and company…",
    SessionStatus.GENERATING: "Designing your tailored question bank…",
}


@ui.page("/session/{session_id}")
async def session_page(session_id: str) -> None:
    user_id = require_user_id()
    if user_id is None:
        return
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        notify_error("Invalid session.")
        ui.navigate.to("/")
        return
    container = get_container()

    with theme.frame("Session"):

        @ui.refreshable
        async def body() -> None:
            prep = await container.sessions.get_session(sid, user_id)
            if prep is None:
                ui.label("Session not found.").classes("text-negative")
                return

            with ui.row().classes("glass p-5 w-full items-center justify-between fade-up"):
                with ui.column().classes("gap-1"):
                    ui.label(prep.target_role).classes("display text-2xl font-extrabold")
                    ui.label(f"{prep.target_company}  ·  {prep.seniority.label}").classes(
                        "ink-muted text-sm"
                    )
                theme.status_badge(prep.status.value, _status_color(prep.status))

            if prep.status == SessionStatus.FAILED:
                with ui.column().classes("glass p-6 gap-2 w-full items-start fade-up d1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("error", size="22px").classes("text-[color:var(--rose)]")
                        ui.label("Preparation failed").classes("font-bold")
                    ui.label(prep.error_message or "Something went wrong.").classes("ink-muted")
                    ui.button(
                        "Retry", icon="refresh", on_click=lambda: _retry(container, prep.id, body)
                    ).classes("cta").props("unelevated")
                return

            if prep.status != SessionStatus.READY:
                with ui.column().classes("glass p-10 items-center gap-3 w-full fade-up d1"):
                    ui.spinner("gears", size="xl", color="primary")
                    ui.label(_PROGRESS_TEXT.get(prep.status, "Working…")).classes(
                        "ink-muted shimmer"
                    )
                    ui.label("This usually takes 10-30 seconds.").classes("ink-muted text-xs")
                return

            _render_ready(container, prep, body)

        await body()

        async def poll() -> None:
            prep = await container.sessions.get_session(sid, user_id)
            if prep is None:
                return
            if prep.status in (SessionStatus.READY, SessionStatus.FAILED):
                timer.active = False
            await body.refresh()

        timer = ui.timer(2.0, poll, active=True)
        # Stop polling promptly if already terminal on first load.
        first = await container.sessions.get_session(sid, user_id)
        if first is not None and first.status in (SessionStatus.READY, SessionStatus.FAILED):
            timer.active = False


def _render_ready(container: Container, prep: PrepSession, body: Any) -> None:
    brief = container.sessions.parse_brief(prep)
    questions = container.sessions.parse_questions(prep)

    with ui.row().classes("w-full gap-2 fade-up d1"):
        if prep.interview_status in (
            InterviewStatus.NOT_STARTED,
            InterviewStatus.IN_PROGRESS,
        ):
            label = (
                "Resume mock interview"
                if (prep.interview_status == InterviewStatus.IN_PROGRESS)
                else "Start mock interview"
            )
            ui.button(
                label,
                icon="record_voice_over",
                on_click=lambda: ui.navigate.to(f"/session/{prep.id}/interview"),
            ).classes("cta").props("unelevated")
        if prep.interview_status == InterviewStatus.EVALUATED:
            ui.button(
                "View feedback report",
                icon="assessment",
                on_click=lambda: ui.navigate.to(f"/session/{prep.id}/report"),
            ).props("outline color=secondary")
        elif prep.interview_status in (InterviewStatus.COMPLETED, InterviewStatus.EVALUATING):
            ui.button(
                "Continue to feedback",
                icon="assessment",
                on_click=lambda: ui.navigate.to(f"/session/{prep.id}/interview"),
            ).props("outline color=secondary")

    with (
        ui.tabs()
        .classes("w-full fade-up d2")
        .props("active-color=primary indicator-color=primary") as tabs
    ):
        brief_tab = ui.tab("Research brief", icon="travel_explore")
        questions_tab = ui.tab("Question bank", icon="quiz")
        plan_tab = ui.tab("Study plan", icon="checklist")
    with ui.tab_panels(tabs, value=brief_tab).classes("w-full"):
        with ui.tab_panel(brief_tab):
            _render_brief(brief)
        with ui.tab_panel(questions_tab):
            _render_questions(questions)
        with ui.tab_panel(plan_tab):
            _render_plan(questions)


def _render_brief(brief: ResearchBrief | None) -> None:
    if brief is None:
        ui.label("No brief available.")
        return
    with ui.column().classes("glass p-5 gap-3 w-full"):
        ui.label(brief.role_summary).classes("text-base leading-relaxed")
        _chip_section("Key competencies", brief.key_competencies)
        with ui.column().classes("glass-2 p-3 gap-1 w-full"):
            ui.label("Likely interview format").classes("font-bold text-sm")
            ui.label(brief.likely_interview_format).classes("ink-muted text-sm")
        _chip_section("Company values", brief.company_values)
        _chip_section("Signals to emphasize", brief.signals_to_emphasize)
        if brief.inferred_assumptions:
            with ui.expansion("Inferred assumptions (not stated in inputs)").classes("w-full"):
                for item in brief.inferred_assumptions:
                    ui.label(f"• {item}").classes("ink-muted text-sm")


def _render_questions(questions: QuestionBank | None) -> None:
    if questions is None:
        ui.label("No questions available.")
        return
    for title, items in (
        ("Technical", questions.technical),
        ("Behavioral", questions.behavioral),
        ("Company & values", questions.company),
    ):
        theme.section_title(f"{title}  ·  {len(items)}")
        for q in items:
            with ui.expansion(q.question).classes("w-full"):
                with ui.row().classes("gap-2 items-center"):
                    theme.status_badge(q.difficulty.value, "amber")
                    ui.label(q.target_competency).classes("ink-muted text-xs")
                ui.label("Rubric").classes("font-bold text-sm mt-1")
                ui.label(q.rubric).classes("ink-muted text-sm")


def _render_plan(questions: QuestionBank | None) -> None:
    if questions is None or not questions.study_plan:
        ui.label("No study plan available.")
        return
    with ui.column().classes("glass p-5 gap-3 w-full"):
        for i, step in enumerate(questions.study_plan, start=1):
            with ui.row().classes("items-start gap-3"):
                ui.label(f"{i:02d}").classes("mono text-[color:var(--teal)] font-bold")
                ui.label(step).classes("text-sm leading-relaxed")


def _chip_section(title: str, items: list[str]) -> None:
    if not items:
        return
    ui.label(title).classes("font-bold text-sm mt-1")
    with ui.row().classes("flex-wrap gap-2"):
        for item in items:
            ui.label(item).classes("pill")


async def _retry(container: Container, session_id: uuid.UUID, body: Any) -> None:
    from nicegui import background_tasks

    background_tasks.create(container.sessions.run_pipeline(session_id))
    await body.refresh()


def _status_color(status: SessionStatus) -> str:
    return {
        SessionStatus.PENDING: "grey",
        SessionStatus.RESEARCHING: "blue",
        SessionStatus.GENERATING: "blue",
        SessionStatus.READY: "green",
        SessionStatus.FAILED: "red",
    }.get(status, "grey")
