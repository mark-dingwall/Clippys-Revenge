#!/usr/bin/env python3
"""Unified runner — tattoy plugin entry point.

Reads CLIPPY_EFFECTS env var (comma-separated), loads effect class(es),
wraps in UnifiedEffect, and runs the protocol loop.
"""
from __future__ import annotations

import importlib
import os
import random
import sys

from clippy.harness import run
from clippy.unified import UnifiedEffect


def _load_effect_class(effect_name: str):
    """Load an effect class by name from clippy.effects."""
    from clippy.effects import discover_effects
    effects = discover_effects()
    if effect_name not in effects:
        raise ValueError(f"Unknown effect: {effect_name}")
    meta = effects[effect_name]
    module = importlib.import_module(f"clippy.effects.{os.path.basename(meta['module_path']).removesuffix('.py')}")
    return getattr(module, meta["class_name"])


def _load_all_selectable_classes() -> list:
    """Discover all non-overlay effects and load their classes."""
    from clippy.effects import discover_effects
    effects = discover_effects()
    classes = []
    for name, meta in sorted(effects.items()):
        if meta.get("overlay"):
            continue
        module = importlib.import_module(
            f"clippy.effects.{os.path.basename(meta['module_path']).removesuffix('.py')}"
        )
        classes.append(getattr(module, meta["class_name"]))
    return classes


if __name__ == "__main__":
    effect_names_raw = os.environ.get("CLIPPY_EFFECTS", "")
    if effect_names_raw:
        names = [n.strip() for n in effect_names_raw.split(",") if n.strip()]
        try:
            effect_classes = [_load_effect_class(name) for name in names]
        except ValueError as exc:
            print(f"clippy: {exc}; loading all effects", file=sys.stderr)
            effect_classes = _load_all_selectable_classes()
    else:
        effect_classes = _load_all_selectable_classes()
    unified = UnifiedEffect(effect_classes, seed=random.randrange(2**32))
    run(unified)
