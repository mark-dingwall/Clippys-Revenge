#!/usr/bin/env python3
"""Profile ALL effects to identify Rust PyO3 optimization targets.

Runs each effect through its full lifecycle, collecting per-phase timing
and cProfile data. Identifies shared hotspots across effects.
"""
import cProfile
import pstats
import io
import time

from clippy.types import PTYUpdate, OutputCells, OutputPixels


def make_update(width: int, height: int) -> PTYUpdate:
    return PTYUpdate(size=(width, height), cells=[], cursor=(0, 0))


def profile_effect(effect, name: str, width: int = 80, height: int = 24, max_ticks: int = 5000):
    """Run an effect through its lifecycle, return timing + cProfile stats."""
    update = make_update(width, height)
    effect.on_pty_update(update)

    tick_count = 0
    total_cells = 0
    total_pixels = 0
    phase_ticks: dict[str, int] = {}
    phase_times: dict[str, float] = {}

    while not effect.is_done and tick_count < max_ticks:
        phase_name = getattr(effect, 'phase', 'UNKNOWN').name if hasattr(getattr(effect, 'phase', None), 'name') else str(getattr(effect, 'phase', 'UNKNOWN'))
        t0 = time.perf_counter()
        outputs = effect.tick()
        elapsed = time.perf_counter() - t0

        phase_ticks[phase_name] = phase_ticks.get(phase_name, 0) + 1
        phase_times[phase_name] = phase_times.get(phase_name, 0) + elapsed

        for out in outputs:
            if isinstance(out, OutputCells):
                total_cells += len(out.cells)
            elif isinstance(out, OutputPixels):
                total_pixels += len(out.pixels)

        tick_count += 1

    return {
        "name": name,
        "tick_count": tick_count,
        "total_cells": total_cells,
        "total_pixels": total_pixels,
        "phase_ticks": phase_ticks,
        "phase_times": phase_times,
        "total_time_ms": sum(phase_times.values()) * 1000,
    }


def profile_serialization(effect, width: int = 80, height: int = 24):
    """Measure serialization cost for a typical frame."""
    update = make_update(width, height)
    effect.on_pty_update(update)

    # Fast-forward to get a frame with content
    last_outputs = []
    for _ in range(200):
        outputs = effect.tick()
        if outputs:
            last_outputs = outputs

    if not last_outputs:
        return {"serial_1k_ms": 0.0, "items_per_frame": 0}

    items = 0
    for out in last_outputs:
        if isinstance(out, OutputCells):
            items += len(out.cells)
        elif isinstance(out, OutputPixels):
            items += len(out.pixels)

    t0 = time.perf_counter()
    for _ in range(1000):
        for out in last_outputs:
            out.to_json()
    serial_time = time.perf_counter() - t0

    return {"serial_1k_ms": serial_time * 1000, "items_per_frame": items}


def cprofile_effect(effect_factory, width: int = 80, height: int = 24, max_ticks: int = 5000):
    """Run cProfile on a full lifecycle."""
    pr = cProfile.Profile()
    effect = effect_factory()
    update = make_update(width, height)
    effect.on_pty_update(update)

    pr.enable()
    tick_count = 0
    while not effect.is_done and tick_count < max_ticks:
        effect.tick()
        tick_count += 1
    pr.disable()

    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(20)
    return s.getvalue()


def main():
    from clippy.effects.fire import FireEffect
    from clippy.effects.invaders import InvadersEffect
    from clippy.effects.grove import GroveEffect
    from clippy.effects.microbes import MicrobesEffect
    from clippy.effects.paperclips import PaperclipsEffect

    effects = [
        ("fire",       lambda: FireEffect(seed=42, idle_secs=0)),
        ("invaders",   lambda: InvadersEffect(seed=42, idle_secs=0)),
        ("grove",      lambda: GroveEffect(seed=42, idle_secs=0)),
        ("microbes",   lambda: MicrobesEffect(seed=42, idle_secs=0)),
        ("paperclips", lambda: PaperclipsEffect(seed=42, idle_secs=0)),
    ]

    for terminal, (w, h) in [("80x24", (80, 24)), ("160x48", (160, 48))]:
        print("=" * 70)
        print(f"ALL EFFECTS — {terminal} terminal")
        print("=" * 70)

        for name, factory in effects:
            print(f"\n--- {name} ---")
            effect = factory()
            stats = profile_effect(effect, name, w, h)
            serial = profile_serialization(factory(), w, h)

            print(f"  Ticks: {stats['tick_count']}  |  Cells: {stats['total_cells']}  |  Pixels: {stats['total_pixels']}")
            print(f"  Total tick time: {stats['total_time_ms']:.1f} ms  |  Avg: {stats['total_time_ms']/max(1,stats['tick_count']):.3f} ms/tick")
            print(f"  Serialization (1k iters): {serial['serial_1k_ms']:.1f} ms  |  Items/frame: {serial['items_per_frame']}")

            print(f"\n  {'Phase':<25} {'Ticks':>6} {'Total(ms)':>10} {'Avg(ms)':>9}")
            print(f"  {'-'*54}")
            for phase in stats["phase_ticks"]:
                ticks = stats["phase_ticks"][phase]
                total_ms = stats["phase_times"][phase] * 1000
                avg_ms = total_ms / ticks if ticks else 0
                print(f"  {phase:<25} {ticks:>6} {total_ms:>10.1f} {avg_ms:>9.3f}")

        # cProfile details for each effect
        print("\n" + "=" * 70)
        print(f"cProfile details — {terminal} — Top 20 by self time")
        print("=" * 70)

        for name, factory in effects:
            print(f"\n{'='*30} {name} {'='*30}")
            print(cprofile_effect(factory, w, h))


if __name__ == "__main__":
    main()
