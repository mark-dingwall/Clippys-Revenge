#!/usr/bin/env python3
"""Microbes effect — colorful dots dashing along curved spline paths.

Inspired by p5.js "teleporting dots": ~80 microbes dash between random
positions along Catmull-Rom spline paths with easing animation, rendered
as pixels with fading trails.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from enum import IntEnum

from clippy.harness import run
from clippy.types import Cell, Color, OutputCells, OutputMessage, PTYUpdate, TTYResize

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOT_COUNT = 80
SWARMING_DURATION = 300   # ~10s @30fps
FADE_DURATION = 60        # ~2s

# Dash timing
MIN_WAIT = 0
MAX_WAIT = 15
MIN_DASH_TIME = 1.0  # seconds
MAX_DASH_TIME = 2.5  # seconds

# Explode intro
EXPLODE_INF_RAD = 20       # pixel-space influence radius
EXPLODE_RND_MULT = 5       # matches JS MOUSE_INF_RND
EXPLODE_MIN_DASH_TIME = 0.2
EXPLODE_MAX_DASH_TIME = 0.6

# Easing
MIN_EASE_POW = 3
MAX_EASE_POW = 6

# Path generation
MIN_PATH_LEN = 4
MAX_PATH_LEN = 8
MIN_PATH_OFF = 3.0
MAX_PATH_OFF = 15.0

# Destination
DEST_RAD = 20
RAND_RAD = 20
DIST_R_MULT = 30.0

# Trail rendering (matches JS DASH_TRAIL / DASH_ACCURACY)
DASH_TRAIL = 0.15       # fraction of curve path visible as trail
TRAIL_SAMPLES = 9       # sample points along trail (JS DASH_ACCURACY)
MIN_STROKE = 2          # min pixel width of microbe body
MAX_STROKE = 4          # max pixel width


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase(IntEnum):
    IDLE = 0
    SWARMING = 1
    FADING = 2
    DONE = 3


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _hsb_to_rgb(h: float, s: float, b: float) -> tuple[float, float, float]:
    """HSB to RGB. h in [0,360), s and b in [0,1]. Returns (r, g, b) in [0,1]."""
    h = h % 360.0
    c = b * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = b - c
    if h < 60:
        r1, g1, b1 = c, x, 0.0
    elif h < 120:
        r1, g1, b1 = x, c, 0.0
    elif h < 180:
        r1, g1, b1 = 0.0, c, x
    elif h < 240:
        r1, g1, b1 = 0.0, x, c
    elif h < 300:
        r1, g1, b1 = x, 0.0, c
    else:
        r1, g1, b1 = c, 0.0, x
    return (r1 + m, g1 + m, b1 + m)


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Catmull-Rom interpolation between p1 and p2 (t in [0,1])."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        2.0 * p1
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def _bresenham_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Integer line rasterization. Returns all pixels from (x0,y0) to (x1,y1)."""
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return points


def _thicken_point(cx: int, cy: int, width: int) -> list[tuple[int, int]]:
    """Return pixels forming a filled shape of given width around (cx, cy).

    width=1 → single point, width=2 → plus shape (5px),
    width=3 → 3×3 block (9px), width=4 → diamond radius 2 (13px).
    """
    if width <= 1:
        return [(cx, cy)]
    if width == 2:
        return [(cx, cy), (cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)]
    if width == 3:
        return [(cx + dx, cy + dy) for dx in range(-1, 2) for dy in range(-1, 2)]
    # width >= 4: diamond with radius 2
    r = width // 2
    return [(cx + dx, cy + dy)
            for dx in range(-r, r + 1)
            for dy in range(-r, r + 1)
            if abs(dx) + abs(dy) <= r]


# ---------------------------------------------------------------------------
# Microbe dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _Microbe:
    fx: float
    fy: float
    path_x: list[float]
    path_y: list[float]
    path_len: int
    color: Color
    next_dash: int       # countdown ticks before starting dash
    dash_inc: float      # per-tick increment to dash_perc
    dash_perc: float     # animation progress [0, 1]
    ease_pow: int        # easing exponent
    stroke_weight: int   # pixel width of the microbe body
    ease_out: bool = False   # True → easeOut (burst); False → animEase (normal)


# ---------------------------------------------------------------------------
# MicrobesEffect
# ---------------------------------------------------------------------------

class MicrobesEffect:
    EFFECT_META = {"name": "microbes", "description": "Colorful microbes dashing along curved paths"}

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
        self._px_height = 0  # height * 2 (pixel space)

        self._microbes: list[_Microbe] = []
        self._swarming_start = 0
        self._fade_start_tick = 0

        # Ghost erasure (cell-space positions)
        self._prev_cell_positions: set[tuple[int, int]] = set()


    # -- Initialization -------------------------------------------------------

    def _init_microbes(self) -> None:
        self._microbes = []
        cx = self._width / 2.0
        cy = self._px_height / 2.0
        for _ in range(DOT_COUNT):
            # Spawn in a tight circle (radius 5) at screen centre
            r = 5.0 * math.sqrt(self._rng.random())
            angle = self._rng.uniform(0, 2 * math.pi)
            fx = cx + r * math.cos(angle)
            fy = cy + r * math.sin(angle)
            fx = max(0.0, min(float(self._width - 1), fx))
            fy = max(0.0, min(float(self._px_height - 1), fy))
            h = self._rng.uniform(0, 360)
            s = self._rng.uniform(0.5, 1.0)
            b = self._rng.uniform(0.6, 1.0)
            rr, g, bl = _hsb_to_rgb(h, s, b)
            color: Color = (rr, g, bl, 1.0)
            ease_pow = self._rng.randint(MIN_EASE_POW, MAX_EASE_POW)
            stroke_w = self._rng.randint(MIN_STROKE, MAX_STROKE)
            m = _Microbe(
                fx=fx, fy=fy,
                path_x=[], path_y=[], path_len=0,
                color=color,
                next_dash=0,
                dash_inc=0.0, dash_perc=0.0,
                ease_pow=ease_pow,
                stroke_weight=stroke_w,
            )
            self._microbes.append(m)

    # -- Path generation ------------------------------------------------------

    def _prepare_dash(self, m: _Microbe, *, delay: int | None = None,
                      x_dest: float | None = None, y_dest: float | None = None) -> None:
        m.ease_out = False
        if delay is not None:
            m.next_dash = delay
        else:
            m.next_dash = self._rng.randint(MIN_WAIT, MAX_WAIT)

        if x_dest is None or y_dest is None:
            angle = self._rng.uniform(0, 2 * math.pi)
            dist = self._rng.uniform(0, DEST_RAD) + self._rng.uniform(0, RAND_RAD)
            x_dest = m.fx + math.cos(angle) * dist
            y_dest = m.fy + math.sin(angle) * dist

        # Clamp destination
        x_dest = max(0.0, min(float(self._width - 1), x_dest))
        y_dest = max(0.0, min(float(self._px_height - 1), y_dest))

        path_len = self._rng.randint(MIN_PATH_LEN, MAX_PATH_LEN)
        m.path_len = path_len

        # Build waypoints: start + random intermediate + end
        m.path_x = [m.fx]
        m.path_y = [m.fy]
        dx = (x_dest - m.fx) / max(1, path_len - 1)
        dy = (y_dest - m.fy) / max(1, path_len - 1)
        for i in range(1, path_len - 1):
            off = self._rng.uniform(MIN_PATH_OFF, MAX_PATH_OFF)
            angle = self._rng.uniform(0, 2 * math.pi)
            px = m.fx + dx * i + math.cos(angle) * off
            py = m.fy + dy * i + math.sin(angle) * off
            px = max(0.0, min(float(self._width - 1), px))
            py = max(0.0, min(float(self._px_height - 1), py))
            m.path_x.append(px)
            m.path_y.append(py)
        m.path_x.append(x_dest)
        m.path_y.append(y_dest)

        dash_time = self._rng.uniform(MIN_DASH_TIME, MAX_DASH_TIME)
        fps = 30.0
        dash_ticks = max(1, int(dash_time * fps))
        m.dash_inc = 1.0 / dash_ticks
        m.dash_perc = 0.0
        m.ease_pow = self._rng.randint(MIN_EASE_POW, MAX_EASE_POW)

    # -- Animation ------------------------------------------------------------

    @staticmethod
    def _anim_ease(perc: float, power: int) -> float:
        """Acceleration/deceleration easing (smooth in and out)."""
        if perc < 0.5:
            return 0.5 * ((2.0 * perc) ** power)
        return 1.0 - 0.5 * ((2.0 * (1.0 - perc)) ** power)

    @staticmethod
    def _ease_out(perc: float, power: int) -> float:
        """Ease-out (starts fast, decelerates). Used for explode burst."""
        return 1.0 - (1.0 - perc) ** power

    def _calc_pos(self, m: _Microbe, perc: float) -> tuple[float, float]:
        """Compute position along the Catmull-Rom path at progress perc."""
        n = m.path_len
        if n < 2:
            return (m.fx, m.fy)
        # Map perc to segment
        seg_count = n - 1
        raw = perc * seg_count
        seg = int(raw)
        seg = min(seg, seg_count - 1)
        t = raw - seg

        # Catmull-Rom needs 4 control points; clamp indices
        i0 = max(0, seg - 1)
        i1 = seg
        i2 = min(seg + 1, n - 1)
        i3 = min(seg + 2, n - 1)

        x = _catmull_rom(m.path_x[i0], m.path_x[i1], m.path_x[i2], m.path_x[i3], t)
        y = _catmull_rom(m.path_y[i0], m.path_y[i1], m.path_y[i2], m.path_y[i3], t)
        return (x, y)

    def _update_microbe(self, m: _Microbe) -> None:
        if m.next_dash > 0:
            m.next_dash -= 1
            if m.next_dash == 0 and m.path_len == 0:
                self._prepare_dash(m, delay=0)
            return

        if m.path_len == 0:
            self._prepare_dash(m, delay=0)
            return

        m.dash_perc += m.dash_inc
        # Compute eased head position (clamped to [0,1] for calc_pos)
        head_perc = min(1.0, m.dash_perc)
        if m.ease_out:
            eased = self._ease_out(head_perc, m.ease_pow)
        else:
            eased = self._anim_ease(head_perc, m.ease_pow)
        x, y = self._calc_pos(m, eased)

        # Clamp to bounds
        x = max(0.0, min(float(self._width - 1), x))
        y = max(0.0, min(float(self._px_height - 1), y))

        m.fx = x
        m.fy = y

        # JS allows dashPerc up to 1 + DASH_TRAIL so the trail finishes
        if m.dash_perc > 1.0 + DASH_TRAIL:
            self._prepare_dash(m)

    # -- Explode intro --------------------------------------------------------

    def _apply_explode(self) -> None:
        """Burst all microbes outward from screen centre (JS mouseClicked mechanic)."""
        cx = self._width / 2.0
        cy = self._px_height / 2.0
        for m in self._microbes:
            vx = m.fx - cx
            vy = m.fy - cy
            dist = math.hypot(vx, vy)
            if dist < 0.001:
                angle = self._rng.uniform(0, 2 * math.pi)
                vx = math.cos(angle)
                vy = math.sin(angle)
                dist = 1.0
            nx = vx / dist
            ny = vy / dist
            force = (1.0 - dist / EXPLODE_INF_RAD) * EXPLODE_INF_RAD
            force *= self._rng.uniform(1, 1 + EXPLODE_RND_MULT)
            dest_x = max(0.0, min(float(self._width - 1), m.fx + nx * force))
            dest_y = max(0.0, min(float(self._px_height - 1), m.fy + ny * force))
            m.path_x = [m.fx, dest_x]
            m.path_y = [m.fy, dest_y]
            m.path_len = 2
            dash_time = self._rng.uniform(EXPLODE_MIN_DASH_TIME, EXPLODE_MAX_DASH_TIME)
            m.dash_inc = 1.0 / max(1, int(dash_time * 30))
            m.dash_perc = 0.0
            m.ease_pow = self._rng.randint(MIN_EASE_POW, MAX_EASE_POW)
            m.ease_out = True
            m.next_dash = 0

    # -- Scheduling -----------------------------------------------------------

    def _start_effect(self) -> None:
        self._init_microbes()
        self._apply_explode()
        self._swarming_start = self._tick_count
        self._phase = Phase.SWARMING

    def _reset_state(self) -> None:
        self._microbes = []
        self._swarming_start = 0
        self._fade_start_tick = 0
        self._prev_cell_positions = set()

    def _pick_delay(self) -> int:
        return round(self._rng.uniform(0.75, 1.25) * self._idle_secs * 30)

    # -- Protocol callbacks ---------------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        w, h = update.size
        if self._phase == Phase.IDLE:
            self._width = w
            self._height = h
            self._px_height = h * 2
            if self._idle_until == -1:
                self._idle_until = self._tick_count + self._pick_delay()
        elif (w, h) != (self._width, self._height):
            self._handle_resize(w, h)

    def on_resize(self, resize: TTYResize) -> None:
        if self._phase in (Phase.IDLE, Phase.DONE):
            return
        if (resize.width, resize.height) != (self._width, self._height):
            self._handle_resize(resize.width, resize.height)

    def _handle_resize(self, new_w: int, new_h: int) -> None:
        self._width = new_w
        self._height = new_h
        self._px_height = new_h * 2
        self._prev_cell_positions = set()

        # Clamp microbes to new bounds
        for m in self._microbes:
            m.fx = max(0.0, min(float(new_w - 1), m.fx))
            m.fy = max(0.0, min(float(self._px_height - 1), m.fy))
            # Clamp path waypoints too
            for i in range(len(m.path_x)):
                m.path_x[i] = max(0.0, min(float(new_w - 1), m.path_x[i]))
            for i in range(len(m.path_y)):
                m.path_y[i] = max(0.0, min(float(self._px_height - 1), m.path_y[i]))

    # -- Rendering ------------------------------------------------------------

    def _get_fade_alpha(self) -> float:
        if self._phase == Phase.FADING:
            elapsed = self._tick_count - self._fade_start_tick
            return max(0.0, 1.0 - elapsed / FADE_DURATION)
        return 1.0

    def _render(self) -> list[OutputMessage]:
        # cell_colors maps (col, row) -> [top_color, bottom_color]
        cell_colors: dict[tuple[int, int], list[Color | None]] = {}
        current_positions: set[tuple[int, int]] = set()  # pixel-space dedup
        fade_alpha = self._get_fade_alpha()
        max_x = self._width - 1
        max_y = self._px_height - 1

        def _add_pixel(px: int, py: int, color: Color) -> None:
            pos = (max(0, min(max_x, px)), max(0, min(max_y, py)))
            if pos in current_positions:
                return
            current_positions.add(pos)
            col, row = pos[0], pos[1] // 2
            key = (col, row)
            if key not in cell_colors:
                cell_colors[key] = [None, None]
            if pos[1] % 2 == 0:
                cell_colors[key][0] = color  # top half
            else:
                cell_colors[key][1] = color  # bottom half

        for m in self._microbes:
            if m.next_dash > 0 or m.path_len < 2:
                cx = max(0, min(max_x, round(m.fx)))
                cy = max(0, min(max_y, round(m.fy)))
                alpha = m.color[3] * fade_alpha
                if alpha <= 0.0:
                    continue
                color: Color = (m.color[0], m.color[1], m.color[2], alpha)
                for px, py in _thicken_point(cx, cy, m.stroke_weight):
                    _add_pixel(px, py, color)
                continue

            sample_pts: list[tuple[int, int]] = []
            for i in range(TRAIL_SAMPLES):
                raw_perc = m.dash_perc - (DASH_TRAIL / TRAIL_SAMPLES) * i
                clamped = max(0.0, min(1.0, raw_perc))
                if m.ease_out:
                    eased = self._ease_out(clamped, m.ease_pow)
                else:
                    eased = self._anim_ease(clamped, m.ease_pow)
                sx, sy = self._calc_pos(m, eased)
                sx = max(0.0, min(float(max_x), sx))
                sy = max(0.0, min(float(max_y), sy))
                sample_pts.append((round(sx), round(sy)))

            sample_pts.reverse()
            n_samples = len(sample_pts)

            for idx in range(n_samples):
                t = idx / max(1, n_samples - 1)
                seg_alpha = (0.3 + 0.7 * t) * fade_alpha
                if seg_alpha <= 0.0:
                    continue

                sw = max(1, round(1 + (m.stroke_weight - 1) * t))
                color = (m.color[0], m.color[1], m.color[2], seg_alpha)

                if idx < n_samples - 1:
                    line_pts = _bresenham_line(
                        sample_pts[idx][0], sample_pts[idx][1],
                        sample_pts[idx + 1][0], sample_pts[idx + 1][1],
                    )
                else:
                    line_pts = [sample_pts[idx]]

                for lx, ly in line_pts:
                    for px, py in _thicken_point(lx, ly, sw):
                        _add_pixel(px, py, color)

        # Convert cell_colors to Cell list
        cells: list[Cell] = []
        for (col, row), (top, bottom) in cell_colors.items():
            if top is not None and bottom is not None:
                cells.append(Cell(character="\u2580", coordinates=(col, row),
                                  fg=top, bg=bottom))
            elif top is not None:
                cells.append(Cell(character="\u2580", coordinates=(col, row),
                                  fg=top, bg=None))
            else:
                cells.append(Cell(character="\u2584", coordinates=(col, row),
                                  fg=bottom, bg=None))

        # Ghost erasure (cell-space)
        current_cell_positions = set(cell_colors.keys())
        ghost_cells = [
            Cell(character=" ", coordinates=pos, fg=None, bg=None)
            for pos in self._prev_cell_positions - current_cell_positions
            if 0 <= pos[0] < self._width and 0 <= pos[1] < self._height
        ]
        self._prev_cell_positions = current_cell_positions

        all_cells = ghost_cells + cells
        if not all_cells:
            return []
        return [OutputCells(cells=all_cells)]

    # -- Phase transitions ----------------------------------------------------

    def _update_phase(self) -> None:
        if self._phase == Phase.SWARMING:
            if self._tick_count - self._swarming_start >= SWARMING_DURATION:
                self._phase = Phase.FADING
                self._fade_start_tick = self._tick_count
        elif self._phase == Phase.FADING:
            if self._get_fade_alpha() <= 0.0:
                self._phase = Phase.DONE

    # -- Main tick ------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def cancel(self) -> None:
        """Begin fading from any active phase."""
        if self._phase == Phase.SWARMING:
            self._phase = Phase.FADING
            self._fade_start_tick = self._tick_count

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

        # Update microbes
        for m in self._microbes:
            self._update_microbe(m)

        # Render before phase transition (freeze fix: last fading frame erases cleanly)
        result = self._render()

        # Phase transitions
        self._update_phase()

        return result


if __name__ == "__main__":
    run(MicrobesEffect())
