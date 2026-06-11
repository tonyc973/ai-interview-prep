"""Registration page."""

from __future__ import annotations

from nicegui import ui

from app.container import get_container
from app.middleware.auth import login_user
from app.services.auth import AuthError
from app.ui import theme
from app.ui.util import notify_error, notify_ok, request_ip


@ui.page("/register")
def register_page() -> None:
    container = get_container()
    min_len = container.settings.password_min_length

    with theme.auth_frame(
        "Get started free",
        "Your unfair advantage.",
        "Create an account and let a multi-agent crew research the role, build your "
        "question bank, and grill you in a realistic mock interview.",
    ):
        ui.label("Create your account").classes("display text-2xl font-bold")
        ui.label("Takes about ten seconds.").classes("ink-muted text-sm")
        with ui.column().classes("glass p-6 gap-3 w-full mt-1"):
            email = ui.input("Email").props("type=email autofocus outlined dense").classes("w-full")
            password = ui.input("Password").props("type=password outlined dense").classes("w-full")
            ui.label(
                f"At least {min_len} characters; avoid common or guessable passwords."
            ).classes("ink-muted text-xs")
            error = ui.label("").classes("text-[color:var(--rose)] text-sm")

            async def submit() -> None:
                error.set_text("")
                button.props("loading")
                try:
                    user = await container.auth.register(email.value or "", password.value or "")
                except AuthError as exc:
                    error.set_text(exc.user_message)
                    notify_error(exc.user_message)
                    return
                finally:
                    button.props(remove="loading")
                try:
                    await container.auth.authenticate(
                        email.value or "", password.value or "", ip=request_ip()
                    )
                except AuthError:
                    ui.navigate.to("/login")
                    return
                login_user(user)
                notify_ok("Account created.")
                ui.navigate.to("/")

            password.on("keydown.enter", submit)
            button = (
                ui.button("Create account", on_click=submit)
                .classes("w-full cta")
                .props("unelevated")
            )
        with ui.row().classes("w-full justify-center text-sm gap-1"):
            ui.label("Already have an account?").classes("ink-muted")
            ui.link("Sign in", "/login").classes("text-[color:var(--teal)]")
