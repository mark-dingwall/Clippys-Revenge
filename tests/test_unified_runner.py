"""Tests for clippy.unified_runner — entry point loading."""
from __future__ import annotations

import pytest

from clippy.unified_runner import _load_effect_class, _load_all_selectable_classes


def test_load_effect_class_fire():
    from clippy.effects.fire import FireEffect
    cls = _load_effect_class("fire")
    assert cls is FireEffect


def test_load_effect_class_invaders():
    from clippy.effects.invaders import InvadersEffect
    cls = _load_effect_class("invaders")
    assert cls is InvadersEffect


def test_load_effect_class_unknown_raises():
    with pytest.raises(ValueError, match="Unknown effect"):
        _load_effect_class("nonexistent")


def test_load_all_selectable_excludes_overlay():
    classes = _load_all_selectable_classes()
    class_names = [c.__name__ for c in classes]
    assert "MascotEffect" not in class_names


def test_load_all_selectable_count():
    classes = _load_all_selectable_classes()
    # 5 non-overlay effects: fire, invaders, grove, microbes, paperclips
    assert len(classes) == 5
