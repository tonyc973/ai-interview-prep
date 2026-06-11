"""Live mock-interview chat page (turn-by-turn)."""

from __future__ import annotations

import uuid

from nicegui import ui

from app.container import get_container
from app.domain.enums import MessageRole
from app.services.interview_service import InterviewState, InterviewStateError
from app.ui import theme
from app.ui.util import notify_error, require_user_id


@ui.page("/session/{session_id}/interview")
async def interview_page(session_id: str) -> None:
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

    with theme.frame("Mock interview"):
        try:
            state = await container.interviews.start(sid, user_id)
        except InterviewStateError as exc:
            notify_error(exc.user_message)
            ui.navigate.to(f"/session/{sid}")
            return

        with ui.row().classes("w-full items-center justify-between fade-up"):
            progress = ui.label(state.progress_label).classes("pill pill-primary")
            ui.button(
                "Back to session",
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/session/{sid}"),
            ).props("flat color=white")

        chat = ui.column().classes("glass w-full gap-3 p-5 max-h-[58vh] overflow-y-auto fade-up d1")
        controls = ui.column().classes("w-full gap-2 fade-up d2")

        async def render(current: InterviewState) -> None:
            progress.set_text(current.progress_label)
            chat.clear()
            with chat:
                for turn in current.turns:
                    _bubble(turn.role, turn.content)
            controls.clear()
            with controls:
                if current.finished:
                    with ui.column().classes("glass p-5 gap-2 w-full items-start"):
                        ui.label("Interview complete 🎉").classes("display text-lg font-bold")
                        ui.label("Generate your scored, evidence-based feedback report.").classes(
                            "ink-muted text-sm"
                        )
                        ui.button(
                            "Get my feedback report",
                            icon="assessment",
                            on_click=lambda: ui.navigate.to(f"/session/{sid}/report"),
                        ).classes("cta").props("unelevated")
                else:
                    answer = ui.textarea("Your answer").props("outlined autogrow").classes("w-full")

                    async def send() -> None:
                        text = (answer.value or "").strip()
                        if not text:
                            notify_error("Please type an answer first.")
                            return
                        send_btn.props("loading")
                        with chat:
                            thinking = ui.row().classes("items-center gap-2 ink-muted shimmer")
                            with thinking:
                                ui.spinner("dots", size="sm", color="primary")
                                ui.label("Interviewer is thinking…")
                        try:
                            new_state = await container.interviews.submit_answer(sid, user_id, text)
                        except InterviewStateError as exc:
                            thinking.delete()
                            send_btn.props(remove="loading")
                            notify_error(exc.user_message)
                            return
                        except Exception as exc:
                            thinking.delete()
                            send_btn.props(remove="loading")
                            notify_error(_safe_error(exc))
                            return
                        await render(new_state)

                    with ui.row().classes("w-full justify-end"):
                        send_btn = (
                            ui.button("Send answer", icon="send", on_click=send)
                            .classes("cta")
                            .props("unelevated")
                        )

        await render(state)


def _bubble(role: MessageRole, content: str) -> None:
    is_interviewer = role == MessageRole.INTERVIEWER
    justify = "justify-start" if is_interviewer else "justify-end"
    with ui.row().classes(f"w-full {justify}"):
        if is_interviewer:
            ui.element("div").classes("brand-dot mt-1").style("width:26px;height:26px;flex:none")
        with ui.column().classes("gap-1 max-w-[80%]"):
            ui.label("Interviewer" if is_interviewer else "You").classes(
                "ink-muted text-[11px] " + ("" if is_interviewer else "self-end")
            )
            klass = "bubble bubble-int" if is_interviewer else "bubble bubble-me"
            ui.label(content).classes(klass)


def _safe_error(exc: Exception) -> str:
    user_message = getattr(exc, "user_message", None)
    return str(user_message) if user_message else "Something went wrong. Please try again."
