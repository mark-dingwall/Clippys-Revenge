#!/usr/bin/env python3
"""Clippy mascot overlay — watches from the corner with gleeful menace."""
from __future__ import annotations

import os
from enum import IntEnum

from clippy.harness import run
from clippy.mascot_render import (
    BLINK_DURATION,
    BLINK_PERIOD,
    CACKLE_FLIP_TICKS,
    EYE_ALPHA_MAX,
    EYE_ALPHA_MIN,
    EYE_PULSE_PERIOD,
    FACE_H,
    FACE_W,
    MARGIN,
    render_mascot,
)
from clippy.types import CursorShakeDetector, OutputCells, OutputMessage, PTYUpdate, TTYResize

FPS = 30

DEMO_WATCHING_TICKS       = 30    # 1s watching
DEMO_IMMINENT_EARLY_TICKS = 150   # 5s raised eyebrows
DEMO_IMMINENT_DEEP_TICKS  = 150   # 5s angry red eyes
DEMO_CACKLING_TICKS       = 150   # 5s cackling


class Phase(IntEnum):
    WATCHING       = 0
    IMMINENT_EARLY = 1
    IMMINENT_DEEP  = 2
    CACKLING       = 3
    DONE           = 4


# ---------------------------------------------------------------------------
# MascotEffect
# ---------------------------------------------------------------------------

class MascotEffect:
    EFFECT_META = {
        "name": "mascot",
        "description": "Clippy watches from the corner with gleeful menace",
        "overlay": True,
    }

    def __init__(self, seed: int | None = None, idle_secs: float | None = None) -> None:
        if idle_secs is None:
            idle_secs = float(os.environ.get("CLIPPY_INTERVAL", "300"))
        self._idle_secs = idle_secs
        self._demo_mode = idle_secs == 0
        self._tick_count = BLINK_DURATION
        self._phase = Phase.WATCHING
        self._width = 0
        self._height = 0
        self._received_first_update = False
        self._imminent_early_start = 0
        self._imminent_deep_start = 0
        self._cackle_start = 0
        self._cackle_end = 0

        # Cursor-shake skip
        self._shake = CursorShakeDetector()
        self._skip_requested = False

    # -- Timing -----------------------------------------------------------

    def _compute_timing(self) -> None:
        if self._demo_mode:
            self._imminent_early_start = DEMO_WATCHING_TICKS
            self._imminent_deep_start  = DEMO_WATCHING_TICKS + DEMO_IMMINENT_EARLY_TICKS
            self._cackle_start         = self._imminent_deep_start + DEMO_IMMINENT_DEEP_TICKS
            self._cackle_end           = self._cackle_start + DEMO_CACKLING_TICKS
        else:
            self._imminent_early_start = round((self._idle_secs - 15) * FPS)
            self._imminent_deep_start  = round((self._idle_secs - 10) * FPS)
            self._cackle_start         = round((self._idle_secs - 5)  * FPS)
            self._cackle_end           = round(self._idle_secs         * FPS)

    # -- Protocol callbacks -----------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        self._width, self._height = update.size
        if self._phase in (Phase.WATCHING, Phase.IMMINENT_EARLY):
            if self._shake.update(update.cursor):
                self._skip_requested = True
        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()

    def on_resize(self, resize: TTYResize) -> None:
        self._width, self._height = resize.width, resize.height
        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()

    # -- Phase ------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def cancel(self) -> None:
        if self._phase not in (Phase.CACKLING, Phase.DONE):
            self._phase = Phase.DONE

    @property
    def is_done(self) -> bool:
        return self._phase == Phase.DONE

    def _update_phase(self) -> None:
        t = self._tick_count
        if self._phase == Phase.WATCHING and t >= self._imminent_early_start:
            self._phase = Phase.IMMINENT_EARLY
        elif self._phase == Phase.IMMINENT_EARLY and t >= self._imminent_deep_start:
            self._phase = Phase.IMMINENT_DEEP
        elif self._phase == Phase.IMMINENT_DEEP and t >= self._cackle_start:
            self._phase = Phase.CACKLING
        elif self._phase == Phase.CACKLING and t >= self._cackle_end:
            if self._demo_mode:
                self._phase = Phase.DONE
            else:
                self._tick_count = BLINK_DURATION
                self._phase = Phase.WATCHING
                self._compute_timing()

    # -- Rendering --------------------------------------------------------

    _PHASE_TO_STATE = {
        Phase.WATCHING: "watching",
        Phase.IMMINENT_EARLY: "imminent_early",
        Phase.IMMINENT_DEEP: "imminent_deep",
        Phase.CACKLING: "cackling",
    }

    def _render(self) -> list[OutputMessage]:
        state = self._PHASE_TO_STATE.get(self._phase)
        if state is None:
            return []
        cells = render_mascot(state, self._tick_count, self._width, self._height)
        return [OutputCells(cells=cells)] if cells else []

    # -- Main tick --------------------------------------------------------

    def tick(self) -> list[OutputMessage]:
        self._tick_count += 1
        if not self._received_first_update:
            return []
        # Cursor-shake: jump to IMMINENT_DEEP if still in early phases
        if self._skip_requested:
            if self._phase in (Phase.WATCHING, Phase.IMMINENT_EARLY):
                t = self._tick_count
                self._phase = Phase.IMMINENT_DEEP
                self._cackle_start = t + round(5 * FPS)
                self._cackle_end   = t + round(10 * FPS)
            self._skip_requested = False
        self._update_phase()
        if self._phase == Phase.DONE:
            return []
        return self._render()


if __name__ == "__main__":
    run(MascotEffect())
