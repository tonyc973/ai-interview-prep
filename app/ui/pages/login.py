"""Login and logout pages."""

from __future__ import annotations

from nicegui import ui

from app.container import get_container
from app.middleware.auth import login_user, logout_user
from app.services.auth import AuthError
from app.ui import theme
from app.ui.util import notify_error, request_ip


@ui.page("/login")
def login_page(redirect_to: str = "") -> None:
    container = get_container()

    with theme.auth_frame(
        "Welcome back",
        "Walk in ready.",
        "Sign in to run AI-powered mock interviews and get scored, evidence-based feedback.",
    ):
        ui.label("Sign in").classes("display text-2xl font-bold")
        ui.label("Continue to your interview prep.").classes("ink-muted text-sm")
        with ui.column().classes("glass p-6 gap-3 w-full mt-1"):
            email = ui.input("Email").props("type=email autofocus outlined dense").classes("w-full")
            password = ui.input("Password").props("type=password outlined dense").classes("w-full")
            error = ui.label("").classes("text-[color:var(--rose)] text-sm")

            async def submit() -> None:
                error.set_text("")
                button.props("loading")
                try:
                    user = await container.auth.authenticate(
                        email.value or "", password.value or "", ip=request_ip()
                    )
                except AuthError as exc:
                    error.set_text(exc.user_message)
                    notify_error(exc.user_message)
                    return
                finally:
                    button.props(remove="loading")
                login_user(user)
                ui.navigate.to(_safe_redirect(redirect_to))

            password.on("keydown.enter", submit)
            button = ui.button("Sign in", on_click=submit).classes("w-full cta").props("unelevated")
        with ui.row().classes("w-full justify-center text-sm gap-1"):
            ui.label("New here?").classes("ink-muted")
            ui.link("Create an account", "/register").classes("text-[color:var(--teal)]")


@ui.page("/logout")
def logout_page() -> None:
    logout_user()
    ui.navigate.to("/login")


def _safe_redirect(target: str) -> str:
    """Only allow same-site relative redirects (no open redirect).

    Browsers normalize backslashes to forward slashes, so ``/\\evil.com`` is read
    by the browser as the protocol-relative ``//evil.com`` — an open redirect off
    site. Normalize backslashes first, then require a path that starts with a
    single ``/`` (a scheme-relative ``//host`` or absolute URL is refused).
    """
    normalized = target.replace("\\", "/")
    if normalized.startswith("/") and not normalized.startswith("//"):
        return target
    return "/"
