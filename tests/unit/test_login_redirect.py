"""Unit tests for login post-auth redirect safety (open-redirect prevention)."""

from __future__ import annotations

import pytest

from app.ui.pages.login import _safe_redirect


@pytest.mark.parametrize(
    "target",
    [
        "/dashboard",
        "/sessions/abc",
        "/",
        "/a?b=c#frag",
    ],
)
def test_safe_redirect_allows_same_site_paths(target: str) -> None:
    assert _safe_redirect(target) == target


@pytest.mark.parametrize(
    "target",
    [
        "",
        "//evil.com",
        "http://evil.com",
        "https://evil.com/path",
        "evil.com",
        "javascript:alert(1)",
        # Backslash variants: browsers normalize "\" to "/", so these are
        # protocol-relative open redirects and must be refused.
        "/\\evil.com",
        "/\\/evil.com",
        "\\\\evil.com",
        "/\\\\evil.com",
        # Control-character variants: browsers strip tab/newline/CR before
        # parsing, so these collapse to "//evil.com" and must be refused.
        "/\t/evil.com",
        "/\n/evil.com",
        "/\r/evil.com",
        "/\r\n/evil.com",
        "/\t\\evil.com",
        "\t//evil.com",
    ],
)
def test_safe_redirect_blocks_off_site_targets(target: str) -> None:
    assert _safe_redirect(target) == "/"
