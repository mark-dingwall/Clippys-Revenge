"""Unified effect — single state machine wrapping an inner effect + mascot overlay."""
from __future__ import annotations

import os
import random
from enum import IntEnum

from clippy.harness import Effect
from clippy.mascot_render import (
    BLINK_DURATION,
    BLINK_PERIOD,
    CACKLE_FLIP_TICKS,
    EYE_PULSE_PERIOD,
    FACE_H,
    FACE_W,
    MARGIN,
    render_mascot,
)
from clippy.types import (
    Cell,
    CursorShakeDetector,
    OutputCells,
    OutputMessage,
    PTYUpdate,
    TTYResize,
)

FPS = 30
_DESTROYED_BG: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class UnifiedPhase(IntEnum):
    WATCHING = 0
    IMMINENT_EARLY = 1
    IMMINENT_DEEP = 2
    ACTIVE = 3
    CACKLING = 4
    DONE = 5


# ---------------------------------------------------------------------------
# UnifiedEffect
# ---------------------------------------------------------------------------

class UnifiedEffect:
    EFFECT_META = {
        "name": "unified",
        "description": "Unified lifecycle: mascot + inner effect",
    }

    def __init__(
        self,
        effect_classes,
        *,
        seed: int | None = None,
        idle_secs: float | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        # Normalize: accept single class or list
        if isinstance(effect_classes, list):
            self._effect_classes = list(effect_classes)
        else:
            self._effect_classes = [effect_classes]
        self._effect_queue: list = []
        self._last_played = None  # anti-repeat across shuffle boundaries
        self._advance_queue()
        if idle_secs is None:
            idle_secs = float(os.environ.get("CLIPPY_INTERVAL", "300"))
        self._idle_secs = idle_secs
        self._demo_mode = idle_secs == 0
        self._phase = UnifiedPhase.WATCHING
        self._shake = CursorShakeDetector()
        self._inner: Effect | None = None
        self._tick_count = BLINK_DURATION  # match mascot init
        self._width = 0
        self._height = 0
        self._received_first_update = False

        # Last PTYUpdate for forwarding to inner effect on creation
        self._last_pty_update: PTYUpdate | None = None
        # Background buffer: snapshot of terminal content at ACTIVE start
        self._bg_buffer: dict[tuple[int, int], Cell] = {}
        # Positions the effect has ever touched (destroyed — stay blank)
        self._touched: set[tuple[int, int]] = set()
        # Mascot render cache: (cache_key) → list[Cell]
        self._mascot_cache_key: tuple | None = None
        self._mascot_cache: list[Cell] = []
        # Persistent frame for delta updates during ACTIVE
        self._frame: dict[tuple[int, int], Cell] = {}
        self._prev_effect_pos: set[tuple[int, int]] = set()
        self._prev_mascot_pos: set[tuple[int, int]] = set()

        # Timing
        self._imminent_early_start = 0
        self._imminent_deep_start = 0
        self._effect_start = 0
        self._cackle_start = 0
        self._cackle_end = 0

    # -- Timing -----------------------------------------------------------

    def _compute_timing(self) -> None:
        if self._demo_mode:
            # Demo: skip straight to ACTIVE (no IMMINENT_DEEP / CACKLING)
            self._imminent_early_start = 0
            self._imminent_deep_start = 0
            self._effect_start = 0
        else:
            total = round(self._idle_secs * FPS)
            self._imminent_early_start = total - round(10 * FPS)
            self._imminent_deep_start = total - round(5 * FPS)
            self._effect_start = total
            # cackle_start/end set when entering CACKLING

    # -- Protocol callbacks -----------------------------------------------

    def _invalidate_on_resize(self) -> None:
        self._mascot_cache_key = None

    def on_pty_update(self, update: PTYUpdate) -> None:
        old_size = (self._width, self._height)
        self._width, self._height = update.size
        if update.size != old_size:
            self._invalidate_on_resize()
        self._last_pty_update = update

        # Forward to inner effect during ACTIVE
        if self._inner is not None and self._phase == UnifiedPhase.ACTIVE:
            self._inner.on_pty_update(update)

        # L+R only during WATCHING and ACTIVE
        if self._phase == UnifiedPhase.WATCHING:
            if self._shake.update(update.cursor):
                self._phase = UnifiedPhase.IMMINENT_DEEP
                self._effect_start = self._tick_count + round(5 * FPS)
                self._shake.reset()
        elif self._phase == UnifiedPhase.ACTIVE:
            if self._shake.update(update.cursor):
                if self._inner is not None:
                    self._inner.cancel()
                self._shake.reset()
        # All other phases: don't call _shake.update() at all

        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()
            if self._demo_mode:
                self._start_inner_effect()

    def on_resize(self, resize: TTYResize) -> None:
        old_size = (self._width, self._height)
        self._width, self._height = resize.width, resize.height
        if (resize.width, resize.height) != old_size:
            self._invalidate_on_resize()
        if self._inner is not None and self._phase == UnifiedPhase.ACTIVE:
            self._inner.on_resize(resize)
        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()
            if self._demo_mode:
                self._start_inner_effect()

    # -- Phase transitions ------------------------------------------------

    @property
    def phase(self) -> UnifiedPhase:
        return self._phase

    def cancel(self) -> None:
        if self._inner is not None and self._phase == UnifiedPhase.ACTIVE:
            self._inner.cancel()
        if self._phase != UnifiedPhase.DONE:
            self._phase = UnifiedPhase.DONE
            self._inner = None
            self._bg_buffer = {}
            self._touched = set()
            self._frame = {}
            self._prev_effect_pos = set()
            self._prev_mascot_pos = set()

    @property
    def is_done(self) -> bool:
        return self._phase == UnifiedPhase.DONE

    def _update_phase(self) -> None:
        t = self._tick_count
        if self._phase == UnifiedPhase.WATCHING and t >= self._imminent_early_start:
            self._phase = UnifiedPhase.IMMINENT_EARLY
        elif self._phase == UnifiedPhase.IMMINENT_EARLY and t >= self._imminent_deep_start:
            self._phase = UnifiedPhase.IMMINENT_DEEP
        elif self._phase == UnifiedPhase.IMMINENT_DEEP and t >= self._effect_start:
            self._start_inner_effect()

    def _advance_queue(self) -> None:
        """Shuffle all effect classes into the queue, with anti-repeat."""
        self._effect_queue = list(self._effect_classes)
        self._rng.shuffle(self._effect_queue)
        # If first item matches last played, rotate it to the end
        if (len(self._effect_queue) > 1
                and self._effect_queue[0] is self._last_played):
            self._effect_queue.append(self._effect_queue.pop(0))

    def _next_effect_class(self):
        """Pop the next effect class from the queue, refilling when empty."""
        if not self._effect_queue:
            self._advance_queue()
        return self._effect_queue.pop(0)

    def _start_inner_effect(self) -> None:
        self._phase = UnifiedPhase.ACTIVE
        self._capture_background()
        self._init_persistent_frame()
        inner_seed = self._rng.randrange(2**32)
        effect_class = self._next_effect_class()
        self._last_played = effect_class
        self._inner = effect_class(seed=inner_seed, idle_secs=0)
        # Forward current terminal state
        if self._last_pty_update is not None:
            self._inner.on_pty_update(self._last_pty_update)
        self._shake.reset()

    def _start_cackling(self) -> None:
        self._phase = UnifiedPhase.CACKLING
        self._inner = None
        self._bg_buffer = {}
        self._touched = set()
        self._frame = {}
        self._prev_effect_pos = set()
        self._prev_mascot_pos = set()
        self._cackle_start = self._tick_count
        self._cackle_end = self._tick_count + round(5 * FPS)

    # -- Compositing ------------------------------------------------------

    def _capture_background(self) -> None:
        """Snapshot the terminal content as the background buffer."""
        self._bg_buffer = {}
        if self._last_pty_update is not None:
            for cell in self._last_pty_update.cells:
                self._bg_buffer[tuple(cell.coordinates)] = cell
        self._touched = set()

    def _overlay(self, base: dict[tuple[int, int], Cell], top: list[Cell]) -> None:
        """Layer top cells onto base dict, inheriting bg when top has bg=None."""
        for cell in top:
            pos = tuple(cell.coordinates)
            if cell.bg is not None:
                base[pos] = cell
            else:
                under = base.get(pos)
                bg = under.bg if under is not None else None
                if bg is None:
                    bg_cell = self._bg_buffer.get(pos)
                    if bg_cell is not None:
                        bg = bg_cell.bg
                base[pos] = Cell(
                    character=cell.character,
                    coordinates=cell.coordinates,
                    fg=cell.fg,
                    bg=bg,
                )

    def _base_cell(self, pos: tuple[int, int]) -> Cell | None:
        """Return the base cell for a position (touched → destroyed, else None/transparent)."""
        if pos in self._touched:
            return Cell(character=" ", coordinates=pos, fg=None, bg=_DESTROYED_BG)
        return None  # Transparent — PTY shows through

    def _init_persistent_frame(self) -> None:
        """Build the initial persistent frame at ACTIVE start."""
        self._frame = {}  # Empty — only touched/effect/mascot positions added
        self._prev_effect_pos = set()
        self._prev_mascot_pos = set()

    def _composite(self, inner_outputs: list[OutputMessage]) -> list[OutputMessage]:
        """Delta-based compositing: restore previous positions, apply new ones."""
        w, h = self._width, self._height
        if w <= 0 or h <= 0:
            return inner_outputs

        frame = self._frame

        # Restore previous mascot positions to base
        for pos in self._prev_mascot_pos:
            base = self._base_cell(pos)
            if base is not None:
                frame[pos] = base
            else:
                frame.pop(pos, None)  # Remove → transparent

        # Restore previous effect positions to base
        for pos in self._prev_effect_pos:
            base = self._base_cell(pos)
            if base is not None:
                frame[pos] = base
            else:
                frame.pop(pos, None)

        # Extract effect cells from inner outputs
        passthrough: list[OutputMessage] = []
        effect_cells: list[Cell] = []
        for msg in inner_outputs:
            if isinstance(msg, OutputCells):
                effect_cells = msg.cells
            else:
                passthrough.append(msg)

        # Apply touched mask for newly touched positions
        destructive = getattr(self._inner, 'destructive', True)
        cur_effect_pos: set[tuple[int, int]] = set()
        for cell in effect_cells:
            pos = tuple(cell.coordinates)
            cur_effect_pos.add(pos)
            if destructive or cell.bg is not None:
                self._touched.add(pos)

        # Overlay effect cells
        self._overlay(frame, effect_cells)

        # Overlay mascot
        cur_mascot_pos: set[tuple[int, int]] = set()
        mascot_msgs = self._render_mascot()
        if mascot_msgs:
            mascot_msg = mascot_msgs[0]
            assert isinstance(mascot_msg, OutputCells)
            for cell in mascot_msg.cells:
                cur_mascot_pos.add(tuple(cell.coordinates))
            self._overlay(frame, mascot_msg.cells)

        self._prev_effect_pos = cur_effect_pos
        self._prev_mascot_pos = cur_mascot_pos

        cells = list(frame.values())
        return passthrough + [OutputCells(cells=cells)] if cells else passthrough

    _PHASE_TO_STATE = {
        UnifiedPhase.WATCHING: "watching",
        UnifiedPhase.IMMINENT_EARLY: "imminent_early",
        UnifiedPhase.IMMINENT_DEEP: "imminent_deep",
        UnifiedPhase.ACTIVE: "active",
        UnifiedPhase.CACKLING: "cackling",
    }

    def _mascot_cache_key_for(self, state: str) -> tuple:
        t = self._tick_count
        if state == "watching":
            blink = t % BLINK_PERIOD < BLINK_DURATION
            return (state, blink, self._width, self._height)
        elif state == "cackling":
            frame = (t // CACKLE_FLIP_TICKS) % 2
            return (state, frame, self._width, self._height)
        else:
            # imminent_early is static; imminent_deep/active pulse by period
            pulse_phase = t % EYE_PULSE_PERIOD
            return (state, pulse_phase, self._width, self._height)

    def _render_mascot(self) -> list[OutputMessage]:
        state = self._PHASE_TO_STATE.get(self._phase)
        if state is None:
            return []
        key = self._mascot_cache_key_for(state)
        if key != self._mascot_cache_key:
            self._mascot_cache = render_mascot(state, self._tick_count, self._width, self._height)
            self._mascot_cache_key = key
        return [OutputCells(cells=self._mascot_cache)] if self._mascot_cache else []

    # -- Main tick --------------------------------------------------------

    def tick(self) -> list[OutputMessage]:
        self._tick_count += 1
        if not self._received_first_update:
            return []

        self._update_phase()

        if self._phase == UnifiedPhase.DONE:
            return []

        if self._phase == UnifiedPhase.ACTIVE:
            assert self._inner is not None
            inner_outputs = self._inner.tick()
            if self._inner.is_done:
                if self._demo_mode:
                    self._phase = UnifiedPhase.DONE
                    return []
                self._start_cackling()
            return self._composite(inner_outputs)

        if self._phase == UnifiedPhase.CACKLING:
            if self._tick_count >= self._cackle_end:
                if self._demo_mode:
                    self._phase = UnifiedPhase.DONE
                    return []
                else:
                    # Loop back to WATCHING
                    self._tick_count = BLINK_DURATION
                    self._phase = UnifiedPhase.WATCHING
                    self._compute_timing()
                    self._shake.reset()
            return self._render_mascot()

        # WATCHING, IMMINENT_EARLY, IMMINENT_DEEP — mascot only
        return self._render_mascot()
