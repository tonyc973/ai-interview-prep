"""UI package. ``register_pages`` imports every page module so their
``@ui.page`` decorators register routes with NiceGUI.
"""

from __future__ import annotations


def register_pages() -> None:
    # Imported for their @ui.page registration side effects.
    from app.ui.pages import (
        account,
        dashboard,
        interview,
        login,
        register,
        report,
        session,
    )

    _ = (account, dashboard, interview, login, register, report, session)
