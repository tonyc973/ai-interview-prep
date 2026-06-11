"""Account page: profile, usage/cost, and session controls."""

from __future__ import annotations

from typing import Any

from nicegui import app, ui

from app.container import get_container
from app.middleware.auth import current_user_email, logout_user
from app.ui import theme
from app.ui.util import require_user_id


@ui.page("/account")
async def account_page() -> None:
    user_id = require_user_id()
    if user_id is None:
        return
    container = get_container()
    settings = container.settings

    daily_cost = await container.usage.user_daily_cost(user_id)
    sessions = await container.sessions.list_sessions(user_id)

    cap = settings.max_cost_per_user_per_day_usd
    with theme.frame("Account"):
        with ui.row().classes("w-full gap-4 flex-wrap items-stretch fade-up"):
            with ui.column().classes("glass p-5 gap-2 flex-1 min-w-[260px]"):
                ui.label("Profile").classes("display text-lg font-bold")
                with ui.row().classes("items-center gap-2"):
                    ui.icon("alternate_email", size="18px").classes("text-[color:var(--teal)]")
                    ui.label(current_user_email() or "—").classes("font-medium")
                ui.label(f"{len(sessions)} prep session(s) created").classes("ink-muted text-sm")

            with ui.column().classes("glass p-5 gap-2 flex-1 min-w-[260px]"):
                ui.label("AI usage today").classes("display text-lg font-bold")
                ui.label(f"${daily_cost:.4f}").classes(
                    "display text-3xl font-extrabold gradient-text"
                )
                ui.label(f"of ${cap:.2f} daily budget").classes("ink-muted text-sm")
                ui.linear_progress(
                    min(daily_cost / cap, 1.0) if cap else 0.0, show_value=False
                ).props("color=primary rounded size=8px").classes("w-full")

        with ui.column().classes("glass p-5 gap-2 w-full fade-up d1"):
            ui.label("Preferences").classes("display text-lg font-bold")
            dark = ui.switch(
                "Dark theme", value=bool(app.storage.user.get("dark_mode", True))
            ).props("color=primary")

            async def _toggle(_e: Any) -> None:
                value = bool(dark.value)
                ui.dark_mode(value)
                ui.run_javascript(
                    f"document.body.classList.{'remove' if value else 'add'}('theme-light')"
                )
                app.storage.user["dark_mode"] = value
                await container.auth.set_dark_mode(user_id, value)

            dark.on_value_change(_toggle)

        ui.button("Log out", icon="logout", on_click=_logout).props(
            "outline color=negative"
        ).classes("fade-up d2 w-fit")


def _logout() -> None:
    logout_user()
    ui.navigate.to("/login")
