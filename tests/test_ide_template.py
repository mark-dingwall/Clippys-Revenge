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
