"""Design system: the aurora/midnight theme, global styles, and page chrome.

One place defines the palette, fonts, and reusable visual primitives (glass
cards, gradient text, pills, score ring, chat bubbles). Dark is the default; a
persisted per-user toggle swaps to a light "paper" variant via a body class.
UI modules contain presentation only — they call services via the container.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from nicegui import app, ui

from app.container import get_container
from app.middleware.auth import current_user_email, current_user_id, logout_user

# Quasar brand colors (component internals); the look is driven by the CSS below.
PRIMARY = "#2dd4bf"
SECONDARY = "#8b5cf6"
ACCENT = "#38bdf8"
POSITIVE = "#34d399"
NEGATIVE = "#fb7185"

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Bricolage+Grotesque:opsz,wght@12..96,400..800&"
    "family=Manrope:wght@400;500;600;700;800&"
    'family=JetBrains+Mono:wght@500;700&display=swap">'
)

_CSS = """
<style>
:root{
  --bg:#060912; --bg2:#0a0f1f; --text:#e9edf8; --muted:#94a1bd;
  --teal:#2dd4bf; --violet:#8b5cf6; --sky:#38bdf8; --amber:#fbbf24;
  --green:#34d399; --rose:#fb7185;
  --surface:rgba(255,255,255,.045); --surface2:rgba(255,255,255,.07);
  --border:rgba(255,255,255,.10); --border2:rgba(255,255,255,.16);
  --radius:20px;
  --glow:0 24px 70px -28px rgba(45,212,191,.35), 0 0 0 1px rgba(255,255,255,.05);
}
html, body{ background:var(--bg); color:var(--text);
  font-family:'Manrope',-apple-system,sans-serif; -webkit-font-smoothing:antialiased; }
.nicegui-content{ padding:0; }
body{
  background-image:
    radial-gradient(1100px 620px at 12% -8%, rgba(139,92,246,.22), transparent 60%),
    radial-gradient(1000px 640px at 96% -4%, rgba(45,212,191,.18), transparent 55%),
    radial-gradient(900px 760px at 50% 118%, rgba(56,189,248,.14), transparent 60%);
  background-attachment:fixed;
}
body::before{ /* fine grain texture */
  content:""; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.05;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
.display{ font-family:'Bricolage Grotesque',sans-serif; letter-spacing:-.025em; line-height:1.04; }
.mono{ font-family:'JetBrains Mono',monospace; }
.gradient-text{
  background:linear-gradient(100deg,var(--teal),var(--sky) 45%,var(--violet));
  -webkit-background-clip:text; background-clip:text; color:transparent;
}
.ink-muted{ color:var(--muted); }

/* Glass surfaces */
.glass{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
  backdrop-filter:blur(16px) saturate(130%); -webkit-backdrop-filter:blur(16px) saturate(130%);
  box-shadow:var(--glow); }
.glass-2{ background:var(--surface2); border:1px solid var(--border); border-radius:16px;
  backdrop-filter:blur(10px); }
.lift{ transition:transform .25s cubic-bezier(.2,.7,.2,1), box-shadow .25s, border-color .25s; }
.lift:hover{ transform:translateY(-4px); border-color:var(--border2);
  box-shadow:0 30px 80px -30px rgba(56,189,248,.4), 0 0 0 1px rgba(255,255,255,.08); }
.hairline{ height:1px; background:linear-gradient(90deg,transparent,var(--border2),transparent); }

/* Header */
.topbar{ background:rgba(8,12,24,.6); backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border); }
.brand-dot{ width:30px;height:30px;border-radius:10px;
  background:conic-gradient(from 200deg,var(--teal),var(--sky),var(--violet),var(--teal));
  box-shadow:0 0 24px -2px rgba(45,212,191,.7); }

/* Quasar overrides */
.q-btn{ border-radius:12px !important; text-transform:none !important; font-weight:600;
  letter-spacing:0; }
.q-btn.bg-primary, .q-btn--standard.text-primary{ color:#04120f !important; }
.cta .q-btn{ background:linear-gradient(100deg,var(--teal),var(--sky)) !important;
  color:#03130f !important; box-shadow:0 16px 40px -16px rgba(45,212,191,.65) !important; }
.q-field--outlined .q-field__control{ border-radius:13px; }
.q-field__control:before{ border-color:var(--border) !important; }
.q-tab{ text-transform:none; font-weight:600; }
.q-tab-panels, .q-tab-panel, .q-tabs{ background:transparent !important; }
.q-expansion-item{ border:1px solid var(--border); border-radius:14px; margin-bottom:.5rem;
  background:var(--surface); overflow:hidden; }

/* Pills */
.pill{ display:inline-flex; align-items:center; gap:.35rem; padding:.18rem .6rem;
  border-radius:999px; font-size:.72rem; font-weight:700; letter-spacing:.02em;
  border:1px solid var(--border); background:var(--surface2); color:var(--text); }
.pill-green{ color:#5ef0c0; border-color:rgba(52,211,153,.35); background:rgba(52,211,153,.12); }
.pill-blue{ color:#7dd3fc; border-color:rgba(56,189,248,.35); background:rgba(56,189,248,.12); }
.pill-amber{ color:#fcd34d; border-color:rgba(251,191,36,.35); background:rgba(251,191,36,.12); }
.pill-red{ color:#fda4af; border-color:rgba(251,113,133,.35); background:rgba(251,113,133,.12); }
.pill-grey{ color:var(--muted); }
.pill-primary{ color:#5ef0c0; border-color:rgba(45,212,191,.4); background:rgba(45,212,191,.12); }
.pill-secondary{ color:#c4b5fd; border-color:rgba(139,92,246,.4); background:rgba(139,92,246,.14); }

/* Chips */
.q-chip{ background:var(--surface2) !important; border:1px solid var(--border) !important;
  color:var(--text) !important; border-radius:10px !important; }

/* Score ring */
.ring{ width:118px;height:118px;border-radius:50%; display:grid; place-items:center;
  background:conic-gradient(var(--teal) calc(var(--p)*1%), rgba(255,255,255,.08) 0);
  position:relative; }
.ring::before{ content:""; position:absolute; inset:8px; border-radius:50%;
  background:rgba(10,14,28,.9); border:1px solid var(--border); }
.ring > div{ position:relative; text-align:center; }

/* Chat bubbles */
.bubble{ max-width:78%; padding:.7rem .95rem; border-radius:16px; line-height:1.5;
  border:1px solid var(--border); }
.bubble-int{ background:var(--surface2); border-bottom-left-radius:5px; }
.bubble-me{ background:linear-gradient(100deg,rgba(45,212,191,.16),rgba(56,189,248,.16));
  border-color:rgba(45,212,191,.3); border-bottom-right-radius:5px; }

/* Animations */
@keyframes fadeUp{ from{opacity:0; transform:translateY(14px);} to{opacity:1; transform:none;} }
.fade-up{ animation:fadeUp .6s cubic-bezier(.2,.7,.2,1) both; }
.d1{animation-delay:.05s}.d2{animation-delay:.12s}.d3{animation-delay:.2s}.d4{animation-delay:.28s}
@keyframes shimmer{ 0%{opacity:.35} 50%{opacity:1} 100%{opacity:.35} }
.shimmer{ animation:shimmer 1.3s ease-in-out infinite; }
@keyframes float{ 0%,100%{transform:translateY(0)} 50%{transform:translateY(-8px)} }

/* Scrollbar */
::-webkit-scrollbar{ width:10px;height:10px }
::-webkit-scrollbar-thumb{ background:rgba(255,255,255,.14); border-radius:10px }
::-webkit-scrollbar-thumb:hover{ background:rgba(255,255,255,.22) }

/* Light ("paper") variant */
body.theme-light{ --bg:#f4f6fb; --text:#0f1730; --muted:#5b6580;
  --surface:rgba(255,255,255,.75); --surface2:rgba(255,255,255,.9);
  --border:rgba(15,23,48,.10); --border2:rgba(15,23,48,.18);
  --glow:0 24px 60px -30px rgba(45,160,180,.35), 0 0 0 1px rgba(15,23,48,.05); }
body.theme-light{ color:var(--text); }
body.theme-light::before{ opacity:.025; }
body.theme-light .topbar{ background:rgba(255,255,255,.7); }
body.theme-light .q-btn.bg-primary{ color:#04120f !important; }
</style>
"""


def apply_head() -> None:
    ui.add_head_html(_FONTS + _CSS)
    ui.colors(
        primary=PRIMARY,
        secondary=SECONDARY,
        accent=ACCENT,
        positive=POSITIVE,
        negative=NEGATIVE,
        dark="#0a0f1f",
        dark_page="#060912",
    )


def _is_dark() -> bool:
    return bool(app.storage.user.get("dark_mode", True))


def _apply_theme_class(is_dark: bool) -> None:
    cls_op = "remove" if is_dark else "add"
    ui.run_javascript(f"document.body.classList.{cls_op}('theme-light')")


def _setup_dark() -> ui.dark_mode:
    is_dark = _is_dark()
    dark = ui.dark_mode(value=is_dark)
    _apply_theme_class(is_dark)
    return dark


async def _toggle_dark(dark: ui.dark_mode) -> None:
    new_value = not _is_dark()
    dark.value = new_value
    app.storage.user["dark_mode"] = new_value
    _apply_theme_class(new_value)
    user_id = current_user_id()
    if user_id is not None:
        await get_container().auth.set_dark_mode(user_id, new_value)


def _header(*, authenticated: bool, dark: ui.dark_mode) -> None:
    with ui.header().classes("topbar items-center justify-between px-5 py-3"):
        with (
            ui.row()
            .classes("items-center gap-3 cursor-pointer")
            .on("click", lambda: ui.navigate.to("/"))
        ):
            ui.element("div").classes("brand-dot")
            with ui.column().classes("gap-0"):
                ui.label("AI Interview Prep").classes("display text-base font-bold leading-none")
                ui.label("rehearse · score · improve").classes(
                    "ink-muted text-[11px] tracking-wide"
                )
        with ui.row().classes("items-center gap-1"):
            if authenticated:
                _nav_btn("space_dashboard", "Dashboard", "/")
                _nav_btn("account_circle", "Account", "/account")
            ui.button(icon="contrast", on_click=lambda: _toggle_dark(dark)).props(
                "flat round color=white size=sm"
            ).tooltip("Toggle theme")
            if authenticated and current_user_email():
                ui.button(icon="logout", on_click=_logout).props(
                    "flat round color=white size=sm"
                ).tooltip("Log out")


def _nav_btn(icon: str, tip: str, path: str) -> None:
    ui.button(icon=icon, on_click=lambda: ui.navigate.to(path)).props(
        "flat round color=white size=sm"
    ).tooltip(tip)


@contextmanager
def frame(page_title: str, *, authenticated: bool = True) -> Iterator[ui.column]:
    """Standard page chrome + a centered content column."""
    apply_head()
    dark = _setup_dark()
    _header(authenticated=authenticated, dark=dark)

    content = ui.column().classes("w-full max-w-5xl mx-auto px-5 py-7 gap-5 items-stretch z-10")
    with content:
        if page_title:
            ui.label(page_title).classes("display text-3xl font-extrabold fade-up")
        yield content


@contextmanager
def auth_frame(eyebrow: str, headline: str, sub: str) -> Iterator[ui.column]:
    """Split hero layout for the login / register pages."""
    apply_head()
    dark = _setup_dark()
    with ui.row().classes("w-full min-h-screen items-stretch gap-0 z-10 flex-wrap"):
        # Left: brand / marketing hero
        with ui.column().classes(
            "flex flex-1 min-w-[360px] p-12 justify-between gap-10 relative overflow-hidden"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.element("div").classes("brand-dot")
                ui.label("AI Interview Prep").classes("display text-lg font-bold")
            with ui.column().classes("gap-4 max-w-md fade-up"):
                ui.label(eyebrow).classes("pill pill-primary w-fit")
                ui.label(headline).classes("display text-5xl font-extrabold leading-[1.05]")
                ui.label(sub).classes("ink-muted text-lg")
                with ui.column().classes("gap-2 mt-2"):
                    for line in (
                        "Role + company research brief",
                        "Tailored question bank with rubrics",
                        "Live, adaptive mock interview",
                        "Scored feedback with a radar chart",
                    ):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("check_circle", size="18px").classes("text-[color:var(--teal)]")
                            ui.label(line).classes("text-sm")
            ui.label("Powered by CrewAI · OpenAI · NiceGUI").classes("ink-muted text-xs")
        # Right: form card
        with ui.column().classes("flex-1 min-w-[360px] items-center justify-center p-6"):
            with ui.column().classes("w-full max-w-md gap-4 fade-up d1"):
                ui.button(icon="contrast", on_click=lambda: _toggle_dark(dark)).props(
                    "flat round color=white size=sm"
                ).classes("self-end").tooltip("Toggle theme")
                yield ui.column().classes("w-full gap-3")


def _logout() -> None:
    logout_user()
    ui.navigate.to("/login")


def status_badge(text: str, color: str) -> None:
    ui.label(text).classes(f"pill pill-{color}")


def section_title(text: str) -> None:
    ui.label(text).classes("display text-lg font-bold mt-2")
