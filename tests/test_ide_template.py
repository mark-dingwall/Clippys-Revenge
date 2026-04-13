"""Tests for clippy.ide_template — IDE background for demo mode."""
from __future__ import annotations

import pytest

from clippy.ide_template import build_template


def test_build_template_dimensions():
    rows = build_template(80, 24)
    assert len(rows) == 24
    assert all(len(row) == 80 for row in rows)


@pytest.mark.parametrize("width,height", [(40, 12), (120, 40), (200, 50)])
def test_build_template_various_sizes(width, height):
    rows = build_template(width, height)
    assert len(rows) == height
    assert all(len(row) == width for row in rows), (
        f"Expected all rows to have width={width}"
    )


def test_build_template_small():
    rows = build_template(10, 5)
    assert len(rows) == 5
    assert all(len(row) == 10 for row in rows)


def test_build_template_has_content():
    rows = build_template(80, 24)
    assert any(row.strip() for row in rows)


def test_three_panel_layout():
    """width=200: two │ separators per content row."""
    rows = build_template(200, 30)
    for row in rows[2:-3]:  # content rows
        assert row.count("│") == 2, f"Expected 2 separators, got {row.count('│')}"


def test_two_panel_layout():
    """width=120: one │ separator per content row."""
    rows = build_template(120, 30)
    for row in rows[2:-3]:
        assert row.count("│") == 1, f"Expected 1 separator, got {row.count('│')}"


def test_single_panel_layout():
    """width=60: no │ separators in content rows."""
    rows = build_template(60, 30)
    for row in rows[2:-3]:
        assert "│" not in row


def test_title_bar_row_zero():
    """Row 0 contains ● and VS Claudde."""
    rows = build_template(120, 30)
    assert "●" in rows[0]
    assert "VS Claudde" in rows[0]


def test_tab_bar_row_one():
    """Row 1 contains invaders.py."""
    rows = build_template(120, 30)
    assert "invaders.py" in rows[1]


def test_status_bar_last_row():
    """Last visible row is the shell prompt."""
    rows = build_template(120, 30)
    # The status bar row is appended but truncated by lines[:height].
    # Last visible row is the shell prompt.
    assert "python3" in rows[-1]


def test_separator_row():
    """Separator row (third from bottom) is all ─ horizontal lines."""
    rows = build_template(120, 30)
    sep = rows[-3]
    assert all(ch == "─" for ch in sep)


def test_gutter_present_wide():
    """width=120: line numbers visible in content rows."""
    rows = build_template(120, 30)
    # Two-panel mode: gutter "   1 " appears in first content row
    assert "   1 " in rows[2]


def test_gutter_absent_narrow():
    """width=30 (m_w<40): no gutter line numbers."""
    rows = build_template(30, 20)
    # Single panel, m_w=30 < 40, gutter_w=0
    # Content starts with code directly, no "   1 " prefix
    assert not rows[2].startswith("   1 ")


def test_very_small_terminal():
    """10×3: no crash, correct dimensions."""
    rows = build_template(10, 3)
    assert len(rows) == 3
    assert all(len(row) == 10 for row in rows)
