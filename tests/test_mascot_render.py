"""Tests for clippy.mascot_render — shared mascot rendering."""
from __future__ import annotations

import pytest

from clippy.mascot_render import (
    CACKLE_FLIP_TICKS,
    FACE_H,
    FACE_W,
    MARGIN,
    render_mascot,
)


VISUAL_STATES = ["watching", "imminent_early", "imminent_deep", "active", "cackling"]
SIZES = [(80, 24), (40, 12), (120, 50)]


def test_watching_returns_cells():
    cells = render_mascot("watching", tick_count=10, width=80, height=24)
    assert len(cells) > 0
    # Check cells are in the bottom-right corner
    corner_x = 80 - FACE_W - MARGIN
    corner_y = 24 - FACE_H - MARGIN
    for cell in cells:
        x, y = cell.coordinates
        assert corner_x <= x < corner_x + FACE_W
        assert corner_y <= y < corner_y + FACE_H


def test_small_terminal_returns_empty():
    assert render_mascot("watching", tick_count=10, width=3, height=3) == []


def test_cackling_alternates_body():
    cells_f0 = render_mascot("cackling", tick_count=0, width=80, height=24)
    cells_f1 = render_mascot("cackling", tick_count=CACKLE_FLIP_TICKS, width=80, height=24)
    chars_f0 = {(c.coordinates, c.character) for c in cells_f0}
    chars_f1 = {(c.coordinates, c.character) for c in cells_f1}
    # Frames should differ (rounded vs double-line corners)
    assert chars_f0 != chars_f1


def test_active_matches_imminent_deep():
    """Active and imminent_deep use the same visual appearance."""
    cells_deep = render_mascot("imminent_deep", tick_count=50, width=80, height=24)
    cells_active = render_mascot("active", tick_count=50, width=80, height=24)
    # Same characters at same positions
    chars_deep = [(c.coordinates, c.character) for c in cells_deep]
    chars_active = [(c.coordinates, c.character) for c in cells_active]
    assert chars_deep == chars_active
    # Same colors
    colors_deep = [(c.fg, c.bg) for c in cells_deep]
    colors_active = [(c.fg, c.bg) for c in cells_active]
    assert colors_deep == colors_active


@pytest.mark.parametrize("state", VISUAL_STATES)
@pytest.mark.parametrize("width,height", SIZES)
def test_all_cells_in_bounds(state, width, height):
    cells = render_mascot(state, tick_count=42, width=width, height=height)
    for cell in cells:
        x, y = cell.coordinates
        assert 0 <= x < width, f"x={x} out of bounds for width={width}"
        assert 0 <= y < height, f"y={y} out of bounds for height={height}"


@pytest.mark.parametrize("state", VISUAL_STATES)
def test_all_colors_in_range(state):
    cells = render_mascot(state, tick_count=42, width=80, height=24)
    for cell in cells:
        if cell.fg is not None:
            assert all(0.0 <= c <= 1.0 for c in cell.fg), f"fg out of range: {cell.fg}"
        if cell.bg is not None:
            assert all(0.0 <= c <= 1.0 for c in cell.bg), f"bg out of range: {cell.bg}"
