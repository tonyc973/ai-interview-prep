"""Evaluation report page with a competency radar chart."""

from __future__ import annotations

import uuid

from nicegui import ui

from app.agents.schemas import EvaluationReport
from app.container import Container, get_container
from app.services.interview_service import InterviewStateError
from app.ui import theme
from app.ui.util import notify_error, require_user_id


@ui.page("/session/{session_id}/report")
async def report_page(session_id: str) -> None:
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

    with theme.frame("Feedback report"):
        report = await container.interviews.get_report(sid, user_id)
        if report is None:
            report = await _generate(container, sid, user_id)
        if report is None:
            return
        _render_report(report, sid)


async def _generate(
    container: Container, sid: uuid.UUID, user_id: uuid.UUID
) -> EvaluationReport | None:
    holder = ui.column().classes("w-full items-center gap-3 p-6")
    with holder:
        ui.spinner(size="lg")
        ui.label("Scoring your interview and writing feedback…").classes("text-gray-600")
    try:
        report = await container.interviews.evaluate(sid, user_id)
    except InterviewStateError as exc:
        holder.clear()
        notify_error(exc.user_message)
        ui.navigate.to(f"/session/{sid}")
        return None
    except Exception as exc:
        holder.clear()
        message = getattr(exc, "user_message", "Could not generate the report. Please try again.")
        with holder:
            ui.icon("error", color="negative", size="32px")
            ui.label(str(message)).classes("text-negative")
            ui.button("Retry", on_click=lambda: ui.navigate.to(f"/session/{sid}/report")).props(
                "color=primary"
            )
        return None
    holder.delete()
    return report


def _render_report(report: EvaluationReport, sid: uuid.UUID) -> None:
    # Hero: score ring + summary + radar side by side.
    with ui.row().classes("w-full gap-4 flex-wrap items-stretch fade-up"):
        with ui.row().classes("glass p-6 items-center gap-5 flex-1 min-w-[300px]"):
            pct = round(report.overall_score / 5 * 100)
            with ui.element("div").classes("ring").style(f"--p:{pct}"):
                with ui.element("div"):
                    ui.label(f"{report.overall_score:.1f}").classes(
                        "display text-3xl font-extrabold gradient-text leading-none"
                    )
                    ui.label("/ 5").classes("ink-muted text-xs")
            with ui.column().classes("gap-1 flex-1"):
                ui.label("Overall performance").classes("pill pill-primary w-fit")
                ui.label(report.summary).classes("text-sm leading-relaxed")
        with ui.column().classes("glass p-3 flex-1 min-w-[300px] items-center"):
            ui.label("Competency radar").classes("ink-muted text-xs self-start px-2 pt-1")
            _render_radar(report)

    with ui.row().classes("w-full gap-4 flex-wrap fade-up d1"):
        _bullet_card("Strengths", report.strengths, "trending_up", "var(--green)")
        _bullet_card("Gaps", report.gaps, "report_problem", "var(--amber)")

    theme.section_title("Per-competency scores")
    for comp in report.competency_scores:
        with ui.column().classes("glass-2 p-4 gap-1 w-full fade-up"):
            with ui.row().classes("items-center justify-between"):
                ui.label(comp.competency).classes("font-bold")
                theme.status_badge(f"{comp.score} / 5", _score_color(comp.score))
            ui.label(comp.rationale).classes("ink-muted text-sm")
            if comp.evidence:
                with ui.expansion("Evidence from your answers").classes("w-full"):
                    for quote in comp.evidence:
                        ui.label(f"“{quote}”").classes("text-sm italic ink-muted")

    if report.model_answers:
        theme.section_title("Model answers")
        for ma in report.model_answers:
            with ui.expansion(ma.question).classes("w-full"):
                ui.label(ma.strong_answer).classes("text-sm leading-relaxed")

    if report.improvement_plan:
        theme.section_title("Prioritized improvement plan")
        with ui.column().classes("glass p-5 gap-3 w-full"):
            for item in sorted(report.improvement_plan, key=lambda i: i.priority):
                with ui.row().classes("items-start gap-3"):
                    theme.status_badge(f"P{item.priority}", "primary")
                    with ui.column().classes("gap-0"):
                        ui.label(item.focus_area).classes("font-bold text-sm")
                        ui.label(item.action).classes("ink-muted text-sm")

    if report.next_steps:
        _bullet_card("Next steps", report.next_steps, "flag", "var(--sky)")

    ui.button(
        "Back to session", icon="arrow_back", on_click=lambda: ui.navigate.to(f"/session/{sid}")
    ).props("flat color=white").classes("mt-2")


def _render_radar(report: EvaluationReport) -> None:
    labels, values = report.radar_series()
    if not labels:
        return
    indicators = [{"name": label, "max": 5} for label in labels]
    option = {
        "tooltip": {
            "backgroundColor": "#0b1020",
            "borderColor": "#2dd4bf",
            "textStyle": {"color": "#e9edf8"},
        },
        "radar": {
            "indicator": indicators,
            "radius": "66%",
            "axisName": {"color": "#94a1bd", "fontSize": 11},
            "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.10)"}},
            "splitArea": {
                "areaStyle": {"color": ["rgba(255,255,255,0.02)", "rgba(255,255,255,0.04)"]}
            },
            "axisLine": {"lineStyle": {"color": "rgba(255,255,255,0.10)"}},
        },
        "series": [
            {
                "type": "radar",
                "data": [{"value": values, "name": "Your scores"}],
                "symbol": "circle",
                "symbolSize": 5,
                "lineStyle": {"color": "#2dd4bf", "width": 2},
                "itemStyle": {"color": "#38bdf8"},
                "areaStyle": {"color": "rgba(45,212,191,0.22)"},
            }
        ],
    }
    ui.echart(option).classes("w-full h-72")


def _bullet_card(title: str, items: list[str], icon: str, color: str) -> None:
    if not items:
        return
    with ui.column().classes("glass p-4 gap-2 flex-1 min-w-[260px]"):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon, size="20px").style(f"color:{color}")
            ui.label(title).classes("font-bold")
        for item in items:
            with ui.row().classes("items-start gap-2"):
                ui.element("div").classes("mt-2").style(
                    f"width:6px;height:6px;border-radius:50%;background:{color};flex:none"
                )
                ui.label(item).classes("text-sm ink-muted")


def _score_color(score: int) -> str:
    if score >= 4:
        return "green"
    if score == 3:
        return "amber"
    return "red"
