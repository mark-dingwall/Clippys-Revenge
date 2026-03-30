#!/usr/bin/env python3
"""Fire effect — smoke wisps shaped by a simplex noise flow field.

Smoke particles ride a time-varying vector field sampled from 3D simplex noise,
producing smooth, coherent wind-current wisps. Each particle has a float position
updated every tick by the flow field plus a small base rise.
"""
from __future__ import annotations

import collections
import heapq
import math
import os
import random
import sys
from enum import IntEnum

from clippy.harness import run
from clippy.noise import noise3
from clippy.types import Cell, Color, OutputCells, OutputMessage, PTYUpdate, TTYResize

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANCEL_FADE_DURATION = 30   # ~1s fast fade when cursor-shake cancels the effect

BURN_DURATION = 60          # ticks a cell burns before charring (~2s @30fps)

SPREAD_PROB_UP = 0.35
SPREAD_PROB_LATERAL = 0.20
SPREAD_PROB_DIAG_UP = 0.15
SPREAD_PROB_DOWN = 0.05

HEAT_DECAY_MAX = 0.18

# Glyph tiers heavy → light; decay increments tier index toward lighter
CHARRED_TIERS = [
    ["█", "@", "■"],    # tier 0 — heaviest
    ["▓", "#", "8"],    # tier 1
    ["▒", "&", "%"],    # tier 2
    ["░", "§", "$"],    # tier 3
    ["+", "~", "*"],    # tier 4
    ["°", ".", ","],    # tier 5 — lightest
    [" "],              # tier 6 — blank (erases glyph, then skipped)
]

DECAY_MIN_TICKS = 9    # ~300ms at 30fps
DECAY_MAX_TICKS = 30   # ~1000ms at 30fps

# Smouldering embers
EMBER_PROB            = 1 / 500 # chance per charred cell to become an ember on spawn
EMBER_LIFETIME        = 300     # ticks before extinguishing
EMBER_EXTINGUISH_TIER = 4       # tier embers convert to on extinguish
EMBER_CHARS           = ["*", "·", "•", "+", "°"]

# Smoke
SMOKE_EMIT_PROB       = 0.17    # chance per ember per tick
SMOKE_START_TIER      = 4       # tier smoke starts at (light)
SMOKE_DECAY_TICKS     = 20      # ticks between smoke tier advances

# Flow field
SECTOR_W              = 8       # cells per flow sector column
SECTOR_H              = 6       # cells per flow sector row
FLOW_UPDATE_TICKS     = 30      # ticks between flow field recomputation (~1s @30fps)

# Noise parameters for flow field generation; tweak to change character of smoke wisps
NOISE_XY_STEP         = 0.7     # spatial frequency for noise sampling
NOISE_TIME_STEP       = 0.5     # temporal frequency
NOISE_OFFSET          = 100.0   # decorrelate direction vs strength samples
NOISE_MAX_PUSH        = 0.5     # max per-tick displacement (cells/tick)

# Random jitter applied to smoke each tick, in addition to flow field and base rise; tweak for more/less turbulent look
SMOKE_X_RAND          = 0.04    # horizontal jitter per tick
SMOKE_BASE_RISE       = -0.01   # base upward drift (cells/tick); negative = up in terminal coords
SMOKE_VEL_LERP        = 0.02    # how fast particle velocity tracks the sector flow each tick


SmokeParticle = collections.namedtuple(
    "SmokeParticle", ["fx", "fy", "vx", "vy", "tier", "last_decay_tick"]
)


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase(IntEnum):
    IDLE = 0
    SPREADING = 1
    BURNING = 2
    WASTELAND = 3
    CANCEL_FADING = 4
    DONE = 5


# ---------------------------------------------------------------------------
# Cell state
# ---------------------------------------------------------------------------

CLEAR = 0
BURNING = 1
CHARRED = 2


# ---------------------------------------------------------------------------
# Color gradient (heat → RGBA), linearly interpolated
# ---------------------------------------------------------------------------

_COLOR_STOPS: list[tuple[float, Color]] = [
    (0.90, (1.0, 1.0, 0.9, 1.0)),
    (0.75, (1.0, 0.95, 0.4, 1.0)),
    (0.60, (1.0, 0.7, 0.0, 1.0)),
    (0.45, (1.0, 0.45, 0.0, 1.0)),
    (0.30, (0.9, 0.2, 0.0, 1.0)),
    (0.20, (0.6, 0.1, 0.0, 1.0)),
    (0.10, (0.3, 0.05, 0.0, 1.0)),
    (0.02, (0.5, 0.5, 0.55, 1.0)),
]

# Character map (heat → character)
_CHAR_THRESHOLDS: list[tuple[float, str]] = [
    (0.80, "█"),
    (0.60, "▓"),
    (0.40, "▒"),
    (0.25, "░"),
    (0.10, "·"),
    (0.02, "•"),
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _heat_to_color_interp(heat: float) -> Color:
    """Map heat value to RGBA color via linear interpolation (internal)."""
    if heat >= _COLOR_STOPS[0][0]:
        return _COLOR_STOPS[0][1]
    if heat <= _COLOR_STOPS[-1][0]:
        return _COLOR_STOPS[-1][1]
    for i in range(len(_COLOR_STOPS) - 1):
        h_hi, c_hi = _COLOR_STOPS[i]
        h_lo, c_lo = _COLOR_STOPS[i + 1]
        if heat >= h_lo:
            t = (heat - h_lo) / (h_hi - h_lo)
            return (
                _lerp(c_lo[0], c_hi[0], t),
                _lerp(c_lo[1], c_hi[1], t),
                _lerp(c_lo[2], c_hi[2], t),
                _lerp(c_lo[3], c_hi[3], t),
            )
    raise AssertionError("unreachable: heat_to_color fell through all stops")


# Pre-computed 256-entry LUT: index i → color for heat = i/255
_HEAT_LUT: list[Color] = [_heat_to_color_interp(i / 255.0) for i in range(256)]


def heat_to_color(heat: float) -> Color:
    """Map heat value [0,1] to RGBA color via pre-computed LUT."""
    idx = max(0, min(255, int(heat * 255.0)))
    return _HEAT_LUT[idx]


def heat_to_char(heat: float) -> str:
    """Map heat value to a display character."""
    for threshold, ch in _CHAR_THRESHOLDS:
        if heat >= threshold:
            return ch
    return " "


def _dim_color(c: Color, factor: float) -> Color:
    """Dim a color by a factor, preserving alpha."""
    return (c[0] * factor, c[1] * factor, c[2] * factor, c[3])


def _fade_color(c: Color, alpha: float) -> Color:
    """Adjust the alpha of a color."""
    return (c[0], c[1], c[2], c[3] * alpha)


# ---------------------------------------------------------------------------
# Neighbor offsets with spread probabilities
# ---------------------------------------------------------------------------

_SPREAD_DIRS: list[tuple[int, int, float]] = [
    (0, -1, SPREAD_PROB_UP),         # up
    (-1, 0, SPREAD_PROB_LATERAL),    # left
    (1, 0, SPREAD_PROB_LATERAL),     # right
    (-1, -1, SPREAD_PROB_DIAG_UP),   # diag up-left
    (1, -1, SPREAD_PROB_DIAG_UP),    # diag up-right
    (0, 1, SPREAD_PROB_DOWN),        # down
]


# ---------------------------------------------------------------------------
# FireEffect
# ---------------------------------------------------------------------------

class FireEffect:
    EFFECT_META = {"name": "fire", "description": "Fire with flow-field smoke wisps"}

    def __init__(self, seed: int | None = None, idle_secs: float | None = None) -> None:
        self._rng = random.Random(seed)
        if idle_secs is None:
            idle_secs = float(os.environ.get("CLIPPY_INTERVAL", "300"))
        self._idle_secs = idle_secs
        self._phase = Phase.IDLE
        self._tick_count = 0
        self._idle_until = -1
        self._width = 0
        self._height = 0

        # Grids (initialized on first PTYUpdate)
        self._cell_state: list[list[int]] = []
        self._ignition_tick: list[list[int]] = []
        self._charred_char: list[list[str]] = []
        self._charred_tier: list[list[int]] = []
        self._decay_interval: list[list[int]] = []
        self._last_decay_tick: list[list[int]] = []
        self._heat: list[list[float]] = []

        # Frontier: BURNING cells with at least one CLEAR neighbor
        self._frontier: set[tuple[int, int]] = set()
        self._burning_positions: set[tuple[int, int]] = set()

        # Counters for O(1) phase checks
        self._clear_count = 0
        self._burning_count = 0
        self._charred_count = 0
        self._charred_positions: set[tuple[int, int]] = set()

        # Ember and smoke state
        self._is_ember: list[list[bool]] = []
        self._ember_ignition_tick: list[list[int]] = []
        self._ember_count: int = 0
        self._ember_positions: set[tuple[int, int]] = set()
        self._smoke: list[SmokeParticle] = []
        self._hot_list: list[tuple[int, int]] = []
        self._is_hot: list[list[bool]] = []
        self._shimmer_cells: list[tuple[int, int]] = []
        self._heat_rng = random.Random(0)

        # Flow field state (sector grid, recomputed every FLOW_UPDATE_TICKS)
        self._flow_dir: list[list[float]] = []    # direction degrees per sector
        self._flow_str: list[list[float]] = []    # push strength per sector
        self._flow_cols: int = 0
        self._flow_rows: int = 0
        self._last_flow_update: int = -FLOW_UPDATE_TICKS  # force update on first tick

        self._decay_heap: list[tuple[int, int, int]] = []

        self._cancel_fade_start = 0


    # -- Grid management --------------------------------------------------

    def _init_grids(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._cell_state = [[CLEAR] * width for _ in range(height)]
        self._ignition_tick = [[-1] * width for _ in range(height)]
        self._charred_char = [[""] * width for _ in range(height)]
        self._charred_tier = [[-1] * width for _ in range(height)]
        self._decay_interval = [[0] * width for _ in range(height)]
        self._last_decay_tick = [[0] * width for _ in range(height)]
        self._heat = [[0.0] * width for _ in range(height)]
        self._frontier.clear()
        self._burning_positions.clear()
        self._charred_positions.clear()
        self._ember_positions.clear()
        self._clear_count = width * height
        self._burning_count = 0
        self._charred_count = 0
        self._is_ember = [[False] * width for _ in range(height)]
        self._ember_ignition_tick = [[-1] * width for _ in range(height)]
        self._ember_count = 0
        self._smoke = []
        self._hot_list = []
        self._is_hot = [[False] * width for _ in range(height)]
        self._shimmer_cells = []
        self._decay_heap = []
        self._init_flow_field()

    def _ignite_initial(self) -> None:
        """Ignite 2–3 random cells along the bottom edge."""
        if self._height == 0 or self._width == 0:
            return
        y = self._height - 1
        count = self._rng.randint(2, 3)
        for _ in range(count):
            x = self._rng.randint(0, self._width - 1)
            self._ignite_cell(x, y)

    def _ignite_cell(self, x: int, y: int) -> None:
        if self._cell_state[y][x] != CLEAR:
            return
        self._cell_state[y][x] = BURNING
        self._ignition_tick[y][x] = self._tick_count
        self._clear_count -= 1
        self._burning_count += 1
        self._burning_positions.add((x, y))
        # Add to frontier if it has any CLEAR neighbor
        if self._has_clear_neighbor(x, y):
            self._frontier.add((x, y))
        # Neighbors that were not in frontier might now qualify
        for dx, dy, _ in _SPREAD_DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self._width and 0 <= ny < self._height:
                if self._cell_state[ny][nx] == BURNING and (nx, ny) not in self._frontier:
                    if self._has_clear_neighbor(nx, ny):
                        self._frontier.add((nx, ny))

    def _has_clear_neighbor(self, x: int, y: int) -> bool:
        for dx, dy, _ in _SPREAD_DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self._width and 0 <= ny < self._height:
                if self._cell_state[ny][nx] == CLEAR:
                    return True
        return False

    # -- Flow field -------------------------------------------------------

    def _init_flow_field(self) -> None:
        """Allocate sector grid sized for the current terminal dimensions."""
        self._flow_cols = max(1, (self._width + SECTOR_W - 1) // SECTOR_W)
        self._flow_rows = max(1, (self._height + SECTOR_H - 1) // SECTOR_H)
        self._flow_dir = [[0.0] * self._flow_cols for _ in range(self._flow_rows)]
        self._flow_str = [[0.0] * self._flow_cols for _ in range(self._flow_rows)]
        self._last_flow_update = -FLOW_UPDATE_TICKS  # force recompute on next tick

    def _update_flow_field(self) -> None:
        """Recompute the sector flow field using 3D simplex noise."""
        time_s = self._tick_count / 30.0
        for sy in range(self._flow_rows):
            for sx in range(self._flow_cols):
                nx = sx * NOISE_XY_STEP
                ny = sy * NOISE_XY_STEP
                nt = time_s * NOISE_TIME_STEP
                direction = noise3(nx, ny, nt) * 80.0
                strength = ((noise3(nx + NOISE_OFFSET, ny + NOISE_OFFSET, nt) + 1.0) / 2.0) * NOISE_MAX_PUSH
                self._flow_dir[sy][sx] = direction
                self._flow_str[sy][sx] = strength

    def _flow_for_position(self, fx: float, fy: float) -> tuple[float, float]:
        """Return (dx, dy) flow displacement for a particle at float position (fx, fy)."""
        sx = min(int(fx) // SECTOR_W, self._flow_cols - 1)
        sy = min(int(fy) // SECTOR_H, self._flow_rows - 1)
        sx = max(sx, 0)
        sy = max(sy, 0)
        rad = math.radians(self._flow_dir[sy][sx])
        strength = self._flow_str[sy][sx]
        dx = math.sin(rad) * strength
        dy = -math.cos(rad) * strength  # negative = up in terminal coords
        return dx, dy

    # -- Protocol callbacks -----------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        w, h = update.size
        if self._phase == Phase.IDLE:
            self._width = w
            self._height = h
            if self._idle_until == -1:
                self._idle_until = self._tick_count + self._pick_delay()
        elif (w, h) != (self._width, self._height):
            self._handle_resize(w, h)

    def _start_effect(self) -> None:
        if self._width == 0 or self._height == 0:
            self._idle_until = self._tick_count + 1  # retry next tick
            return
        self._init_grids(self._width, self._height)
        self._ignite_initial()
        self._phase = Phase.SPREADING

    def _reset_state(self) -> None:
        self._cell_state = []
        self._ignition_tick = []
        self._charred_char = []
        self._charred_tier = []
        self._decay_interval = []
        self._last_decay_tick = []
        self._heat = []
        self._frontier = set()
        self._burning_positions = set()
        self._charred_positions = set()
        self._ember_positions = set()
        self._clear_count = 0
        self._burning_count = 0
        self._charred_count = 0
        self._is_ember = []
        self._ember_ignition_tick = []
        self._ember_count = 0
        self._smoke = []
        self._hot_list = []
        self._is_hot = []
        self._shimmer_cells = []
        self._decay_heap = []
        self._flow_dir = []
        self._flow_str = []

    def _pick_delay(self) -> int:
        return round(self._rng.uniform(0.75, 1.25) * self._idle_secs * 30)

    def on_resize(self, resize: TTYResize) -> None:
        if self._phase == Phase.IDLE or self._phase == Phase.DONE:
            return
        if (resize.width, resize.height) != (self._width, self._height):
            self._handle_resize(resize.width, resize.height)

    def _handle_resize(self, new_w: int, new_h: int) -> None:
        old_state = self._cell_state
        old_ignition = self._ignition_tick
        old_charred = self._charred_char
        old_charred_tier = self._charred_tier
        old_decay_interval = self._decay_interval
        old_last_decay_tick = self._last_decay_tick
        old_is_ember = self._is_ember
        old_ember_ignition_tick = self._ember_ignition_tick
        old_smoke = self._smoke
        old_w, old_h = self._width, self._height

        self._init_grids(new_w, new_h)

        # Copy overlapping region
        for y in range(min(old_h, new_h)):
            for x in range(min(old_w, new_w)):
                state = old_state[y][x]
                self._cell_state[y][x] = state
                self._ignition_tick[y][x] = old_ignition[y][x]
                if state == BURNING:
                    self._burning_count += 1
                    self._clear_count -= 1
                    self._burning_positions.add((x, y))
                    if self._has_clear_neighbor(x, y):
                        self._frontier.add((x, y))
                elif state == CHARRED:
                    self._clear_count -= 1
                    self._charred_char[y][x] = old_charred[y][x]
                    self._charred_tier[y][x] = old_charred_tier[y][x]
                    self._decay_interval[y][x] = old_decay_interval[y][x]
                    self._last_decay_tick[y][x] = old_last_decay_tick[y][x]
                    if old_is_ember[y][x]:
                        self._is_ember[y][x] = True
                        self._ember_ignition_tick[y][x] = old_ember_ignition_tick[y][x]
                        self._ember_count += 1
                        self._ember_positions.add((x, y))
                    elif old_charred_tier[y][x] < len(CHARRED_TIERS):
                        self._charred_count += 1
                        self._charred_positions.add((x, y))
                        remaining = max(1, old_decay_interval[y][x] - (self._tick_count - old_last_decay_tick[y][x]))
                        heapq.heappush(self._decay_heap, (
                            self._tick_count + remaining, x, y
                        ))

        self._smoke = [
            p for p in old_smoke
            if 0 <= p.fx < new_w and 0 <= p.fy < new_h
        ]
        self._init_flow_field()

        # If new CLEAR cells exist during active phases, regress to SPREADING
        if self._clear_count > 0 and self._phase in (Phase.BURNING, Phase.WASTELAND):
            self._phase = Phase.SPREADING

    # -- Fire simulation --------------------------------------------------

    def _spread_fire(self) -> None:
        """BFS-like cellular automata spread from frontier cells."""
        to_ignite: list[tuple[int, int]] = []
        to_remove: list[tuple[int, int]] = []

        for fx, fy in self._frontier:
            has_clear = False
            for dx, dy, prob in _SPREAD_DIRS:
                nx, ny = fx + dx, fy + dy
                if 0 <= nx < self._width and 0 <= ny < self._height:
                    if self._cell_state[ny][nx] == CLEAR:
                        has_clear = True
                        if self._rng.random() < prob:
                            to_ignite.append((nx, ny))
            if not has_clear:
                to_remove.append((fx, fy))

        for fx, fy in to_remove:
            self._frontier.discard((fx, fy))

        for x, y in to_ignite:
            self._ignite_cell(x, y)

    def _age_cells(self) -> None:
        """Transition BURNING cells to CHARRED after BURN_DURATION."""
        to_char: list[tuple[int, int]] = []
        for fx, fy in self._frontier:
            age = self._tick_count - self._ignition_tick[fy][fx]
            if age >= BURN_DURATION:
                to_char.append((fx, fy))

        # Also scan burning cells not in frontier
        # (they lost all clear neighbors and were removed from frontier)
        for x, y in self._burning_positions:
            if (x, y) in self._frontier:
                continue
            age = self._tick_count - self._ignition_tick[y][x]
            if age >= BURN_DURATION:
                to_char.append((x, y))

        for x, y in to_char:
            if self._cell_state[y][x] == BURNING:
                self._cell_state[y][x] = CHARRED
                self._burning_count -= 1
                self._frontier.discard((x, y))
                self._burning_positions.discard((x, y))

                if self._rng.random() < EMBER_PROB:
                    self._is_ember[y][x] = True
                    self._ember_ignition_tick[y][x] = self._tick_count
                    self._ember_count += 1
                    self._ember_positions.add((x, y))
                    # _charred_count NOT incremented — ember lifecycle is separate
                else:
                    tier = self._rng.randint(0, len(CHARRED_TIERS) // 2 - 1)
                    self._charred_tier[y][x] = tier
                    self._charred_char[y][x] = self._rng.choice(CHARRED_TIERS[tier])
                    self._decay_interval[y][x] = self._rng.randint(DECAY_MIN_TICKS, DECAY_MAX_TICKS)
                    self._last_decay_tick[y][x] = self._tick_count
                    self._charred_count += 1
                    self._charred_positions.add((x, y))
                    heapq.heappush(self._decay_heap, (
                        self._tick_count + self._decay_interval[y][x], x, y
                    ))

    def _decay_charred(self) -> None:
        """Pop charred cells whose decay timer expired from the min-heap."""
        to_remove: list[tuple[int, int]] = []
        while self._decay_heap and self._decay_heap[0][0] <= self._tick_count:
            _, x, y = heapq.heappop(self._decay_heap)
            if (x, y) not in self._charred_positions:
                continue  # stale entry (removed by resize or other)
            tier = self._charred_tier[y][x] + 1
            self._charred_tier[y][x] = tier
            self._last_decay_tick[y][x] = self._tick_count
            if tier < len(CHARRED_TIERS):
                self._charred_char[y][x] = self._rng.choice(CHARRED_TIERS[tier])
                heapq.heappush(self._decay_heap, (
                    self._tick_count + self._decay_interval[y][x], x, y
                ))
            else:
                self._charred_count -= 1
                to_remove.append((x, y))
        for pos in to_remove:
            self._charred_positions.discard(pos)

    def _update_embers(self) -> None:
        """Flicker embers and emit smoke; extinguish aged embers."""
        to_extinguish: list[tuple[int, int]] = []
        for x, y in self._ember_positions:
            age = self._tick_count - self._ember_ignition_tick[y][x]
            if y > 0 and self._rng.random() < SMOKE_EMIT_PROB:
                spawn_fx, spawn_fy = float(x), float(y - 1)
                init_vx, init_vy = self._flow_for_position(spawn_fx, spawn_fy)
                self._smoke.append(SmokeParticle(
                    fx=spawn_fx,
                    fy=spawn_fy,
                    vx=init_vx,
                    vy=init_vy,
                    tier=SMOKE_START_TIER,
                    last_decay_tick=self._tick_count,
                ))
            if age >= EMBER_LIFETIME:
                to_extinguish.append((x, y))

        for x, y in to_extinguish:
            self._is_ember[y][x] = False
            self._ember_ignition_tick[y][x] = -1
            self._ember_count -= 1
            self._ember_positions.discard((x, y))
            self._charred_tier[y][x] = EMBER_EXTINGUISH_TIER
            self._charred_char[y][x] = self._rng.choice(CHARRED_TIERS[EMBER_EXTINGUISH_TIER])
            self._decay_interval[y][x] = self._rng.randint(DECAY_MIN_TICKS, DECAY_MAX_TICKS)
            self._last_decay_tick[y][x] = self._tick_count
            self._charred_positions.add((x, y))
            self._charred_count += 1
            heapq.heappush(self._decay_heap, (
                self._tick_count + self._decay_interval[y][x], x, y
            ))

    def _update_smoke(self) -> None:
        """Move smoke via flow field, apply base rise, decay tiers; collect erase positions."""
        # Recompute flow field if due
        if self._tick_count - self._last_flow_update >= FLOW_UPDATE_TICKS:
            self._update_flow_field()
            self._last_flow_update = self._tick_count

        next_smoke: list[SmokeParticle] = []
        for p in self._smoke:
            # Nudge velocity toward the sector's flow vector
            target_dx, target_dy = self._flow_for_position(p.fx, p.fy)
            vx = p.vx + (target_dx - p.vx) * SMOKE_VEL_LERP
            vy = p.vy + (target_dy - p.vy) * SMOKE_VEL_LERP

            # Apply velocity; SMOKE_BASE_RISE is buoyancy, always active
            new_fx = p.fx + vx + self._rng.uniform(-SMOKE_X_RAND, SMOKE_X_RAND)
            new_fy = p.fy + vy + SMOKE_BASE_RISE

            # Clamp horizontally, remove if risen off screen
            new_fx = max(0.0, min(float(self._width - 1), new_fx))
            if new_fy < 0:
                continue

            # Tier decay
            tier = p.tier
            last_decay = p.last_decay_tick
            if self._tick_count - last_decay >= SMOKE_DECAY_TICKS:
                tier += 1
                last_decay = self._tick_count
            if tier >= len(CHARRED_TIERS):
                continue

            next_smoke.append(SmokeParticle(new_fx, new_fy, vx, vy, tier, last_decay))
        self._smoke = next_smoke

    # -- Visual heat (DOOM fire) ------------------------------------------

    def _compute_heat(self) -> None:
        """DOOM-fire algorithm: seed burning cells, propagate heat upward.

        Uses sparse zeroing (only previous hot cells), direct seeding from
        _burning_positions, and column-bounded propagation to avoid full-grid
        scans.  A per-frame RNG keeps heat deterministic without consuming
        values from the main RNG.  Tracks hot cells via a bool grid + list
        (avoids per-cell tuple hashing).
        """
        heat = self._heat
        w = self._width
        is_hot = self._is_hot
        cell_state = self._cell_state

        # Zero only cells that were hot last frame
        for x, y in self._hot_list:
            heat[y][x] = 0.0
            is_hot[y][x] = False
        hot_list: list[tuple[int, int]] = []
        shimmer: list[tuple[int, int]] = []

        if not self._burning_positions:
            self._hot_list = hot_list
            self._shimmer_cells = shimmer
            return

        # Seed BURNING cells directly from the tracked set; compute bounding box
        min_x = w
        max_x = 0
        min_y = self._height
        max_y = 0
        for x, y in self._burning_positions:
            age = self._tick_count - self._ignition_tick[y][x]
            ratio = age / BURN_DURATION if BURN_DURATION > 0 else 1.0
            if ratio < 0.3:
                heat[y][x] = 1.0
            elif ratio < 0.7:
                heat[y][x] = 0.7
            else:
                heat[y][x] = 0.4
            is_hot[y][x] = True
            hot_list.append((x, y))
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y

        # Propagate upward within bounding box:
        #   columns: burning extent ± margin (heat drifts ±1/row)
        #   rows: from below bottom-most burning up to ~15 rows above topmost
        margin = 15
        col_lo = max(0, min_x - margin)
        col_hi = min(w, max_x + margin + 1)
        row_top = max(0, min_y - margin)
        heat_rng = self._heat_rng
        heat_rng.seed(self._tick_count)
        for y in range(max_y - 1, row_top - 1, -1):
            heat_row = heat[y]
            heat_below = heat[y + 1]
            is_hot_row = is_hot[y]
            any_heat = False
            # Even columns: full propagation with RNG
            for x in range(col_lo & ~1, col_hi, 2):
                drift = heat_rng.randint(-1, 1)
                src_x = max(0, min(w - 1, x + drift))
                decay = heat_rng.random() * HEAT_DECAY_MAX
                val = max(heat_row[x], heat_below[src_x] - decay)
                if val > 0.0:
                    heat_row[x] = val
                    if not is_hot_row[x]:
                        is_hot_row[x] = True
                        hot_list.append((x, y))
                    if val > 0.02 and cell_state[y][x] == CLEAR:
                        shimmer.append((x, y))
                    any_heat = True
            # Odd columns: nearest-neighbor fill (no RNG), alternating direction
            for x in range(col_lo | 1, col_hi, 2):
                if y % 2 == 0:
                    val = heat_row[x - 1] if x > 0 else 0.0
                else:
                    val = heat_row[x + 1] if x + 1 < w else 0.0
                if val > 0.0:
                    heat_row[x] = val
                    if not is_hot_row[x]:
                        is_hot_row[x] = True
                        hot_list.append((x, y))
                    if val > 0.02 and cell_state[y][x] == CLEAR:
                        shimmer.append((x, y))
                    any_heat = True
            if not any_heat:
                break

        self._hot_list = hot_list
        self._shimmer_cells = shimmer

    # -- Rendering --------------------------------------------------------

    def _render(self) -> list[OutputMessage]:
        """Convert grid state + heat to OutputCells using delta rendering.

        Builds a dict buffer of all visible cells, then emits only cells
        whose content changed since last frame.  Ghost erasure handles
        cleanup of vacated positions.
        """
        buf: dict[tuple[int, int], Cell] = {}
        fade_alpha = self._get_fade_alpha()
        w, h = self._width, self._height

        # -- Build buffer of all currently visible cells --

        # Charred cells (background layer)
        for x, y in self._charred_positions:
            ch = self._charred_char[y][x]
            if ch == " ":
                buf[(x, y)] = Cell(
                    character=" ", coordinates=(x, y), fg=None, bg=None,
                )
            else:
                fg: Color = (0.15, 0.1, 0.08, 1.0)
                bg: Color = (0.05, 0.03, 0.02, 1.0)
                if fade_alpha < 1.0:
                    fg = _fade_color(fg, fade_alpha)
                    bg = _fade_color(bg, fade_alpha)
                buf[(x, y)] = Cell(
                    character=ch, coordinates=(x, y), fg=fg, bg=bg,
                )

        if self._burning_count > 0:
            # BURNING cells (overwrite charred at same position if needed)
            for x, y in self._burning_positions:
                h_val = self._heat[y][x]
                color = heat_to_color(h_val)
                ch = heat_to_char(h_val)
                fg = color
                bg = _dim_color(color, 0.6)
                if fade_alpha < 1.0:
                    fg = _fade_color(fg, fade_alpha)
                    bg = _fade_color(bg, fade_alpha)
                buf[(x, y)] = Cell(
                    character=ch, coordinates=(x, y), fg=fg, bg=bg,
                )

            # Heat shimmer — CLEAR cells with heat above threshold
            for x, y in self._shimmer_cells:
                h_val = self._heat[y][x]
                color = heat_to_color(h_val)
                ch = heat_to_char(h_val)
                fg = color
                if fade_alpha < 1.0:
                    fg = _fade_color(fg, fade_alpha)
                buf[(x, y)] = Cell(
                    character=ch, coordinates=(x, y), fg=fg, bg=None,
                )

        # Ember cells (overwrite charred at same position)
        for x, y in self._ember_positions:
            ch = self._rng.choice(EMBER_CHARS)
            r = self._rng.uniform(0.85, 1.0)
            g = self._rng.uniform(0.10, 0.45)
            b = self._rng.random() * 0.05
            fg = (r, g, b, 1.0)
            bg = (0.05, 0.02, 0.01, 1.0)
            if fade_alpha < 1.0:
                fg = _fade_color(fg, fade_alpha)
                bg = _fade_color(bg, fade_alpha)
            buf[(x, y)] = Cell(character=ch, coordinates=(x, y), fg=fg, bg=bg)

        # Smoke overlay (top layer, overwrites charred underneath)
        occupied = self._burning_positions
        for p in self._smoke:
            px = max(0, min(w - 1, round(p.fx)))
            py = max(0, min(h - 1, round(p.fy)))
            if (px, py) in occupied or p.tier >= len(CHARRED_TIERS):
                continue
            ch = CHARRED_TIERS[p.tier][0]
            smoke_fg: Color = (0.467, 0.447, 0.490, 1.0)
            if fade_alpha < 1.0:
                smoke_fg = _fade_color(smoke_fg, fade_alpha)
            buf[(px, py)] = Cell(character=ch, coordinates=(px, py), fg=smoke_fg, bg=None)

        # Emit all cells — tattoy replaces the layer per message,
        # so every visible cell must be sent every frame.
        cells = list(buf.values())

        if not cells:
            return []
        return [OutputCells(cells=cells)]

    def _get_fade_alpha(self) -> float:
        if self._phase == Phase.CANCEL_FADING:
            elapsed = self._tick_count - self._cancel_fade_start
            return max(0.0, 1.0 - elapsed / CANCEL_FADE_DURATION)
        return 1.0

    # -- Phase transitions ------------------------------------------------

    def _update_phase(self) -> None:
        if self._phase == Phase.SPREADING:
            if self._clear_count <= 0:
                self._phase = Phase.BURNING

        elif self._phase == Phase.BURNING:
            if self._burning_count <= 0:
                self._phase = Phase.WASTELAND

        elif self._phase == Phase.WASTELAND:
            if self._charred_count <= 0 and self._ember_count <= 0 and not self._smoke:
                self._phase = Phase.DONE

        elif self._phase == Phase.CANCEL_FADING:
            if self._get_fade_alpha() <= 0.0:
                self._phase = Phase.DONE

    # -- Main tick --------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def cancel(self) -> None:
        """Begin fast fade from any active phase."""
        if self._phase in (Phase.SPREADING, Phase.BURNING, Phase.WASTELAND):
            self._cancel_fade_start = self._tick_count
            self._phase = Phase.CANCEL_FADING

    @property
    def is_done(self) -> bool:
        return self._phase == Phase.DONE

    def tick(self) -> list[OutputMessage]:
        self._tick_count += 1

        if self._phase == Phase.IDLE:
            if self._idle_until >= 0 and self._tick_count >= self._idle_until:
                self._start_effect()
            return []

        if self._phase == Phase.DONE:
            self._reset_state()
            self._idle_until = self._tick_count + self._pick_delay()
            self._phase = Phase.IDLE
            return []

        # Simulation
        if self._phase == Phase.SPREADING:
            self._spread_fire()
            self._age_cells()
            self._decay_charred()
            self._update_embers()
            self._update_smoke()
        elif self._phase == Phase.BURNING:
            self._age_cells()
            self._decay_charred()
            self._update_embers()
            self._update_smoke()
        elif self._phase == Phase.WASTELAND:
            self._decay_charred()
            self._update_embers()
            self._update_smoke()
        elif self._phase == Phase.CANCEL_FADING:
            self._decay_charred()
            self._update_embers()
            self._update_smoke()

        # Visual heat
        if self._burning_count > 0:
            self._compute_heat()

        # Render before phase transition (freeze fix)
        result = self._render()

        # Phase transitions
        self._update_phase()

        return result


if __name__ == "__main__":
    run(FireEffect())
