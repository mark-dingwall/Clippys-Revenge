#!/usr/bin/env python3
"""Grove effect — grass, flowers, vines, trees, bushes, and birds bloom from the terminal bottom."""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from enum import IntEnum

from clippy.harness import run
from clippy.types import Cell, Color, OutputCells, OutputMessage, PTYUpdate, TTYResize

try:
    from clippy_native import fade_color as _fade_color_impl
except ImportError:
    def _fade_color_impl(c: Color, alpha: float) -> Color:  # type: ignore[misc]
        return (c[0], c[1], c[2], c[3] * alpha)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROWING_DURATION = 400
PERCHING_DURATION = 300
FADE_DURATION = 60

GRASS_DENSITY = 0.85
GRASS_MIN_H = 1
GRASS_MAX_H = 15
FLOWER_DENSITY = 0.20
FLOWER_STEM_MIN = 2
FLOWER_STEM_MAX = 10
TREE_COUNT = 8
TREE_TRUNK_MIN = 16
TREE_TRUNK_MAX = 56
TREE_CANOPY_MIN_R = 8
TREE_CANOPY_MAX_R = 22
BUSH_COUNT_RANGE = (7, 14)
BIRD_COUNT_RANGE = (5, 10)
BIRD_SPEED = 1.0
BIRD_FLAP_PERIOD = 8

GRASS_CHARS = ["|", "/", "\\", ",", "`"]
FLOWER_BUD = "o"
FLOWER_OPEN = ["*", "@", "O"]
VINE_CHARS = ["~", "s", "&"]
TRUNK_CHAR = "|"
BARK_CHARS = ["|", "{", "}", ":"]
CANOPY_CHARS = ["@", "#", "&", "*"]
BUSH_CHARS = ["#", "&", "@"]
BIRD_R_HEAD = ">"
BIRD_L_HEAD = "<"
BIRD_R_WINGS = ["/", "\\"]   # frame 0 (up), frame 1 (down)
BIRD_L_WINGS = ["\\", "/"]   # frame 0 (up), frame 1 (down)
BIRD_PERCH = "v"

GRASS_COLORS: list[Color] = [
    (0.1, 0.6, 0.1, 1.0),
    (0.15, 0.7, 0.15, 1.0),
    (0.05, 0.5, 0.05, 1.0),
    (0.2, 0.65, 0.1, 1.0),
    (0.1, 0.55, 0.2, 1.0),
]
FLOWER_COLORS: list[Color] = [
    (1.0, 0.3, 0.5, 1.0),
    (1.0, 0.8, 0.1, 1.0),
    (0.6, 0.2, 0.9, 1.0),
    (1.0, 0.5, 0.1, 1.0),
    (0.3, 0.7, 1.0, 1.0),
    (1.0, 1.0, 0.3, 1.0),
]
BRIGHT_FLOWER_COLORS: list[Color] = [
    (1.0, 0.4, 0.6, 1.0),
    (1.0, 0.9, 0.2, 1.0),
    (0.8, 0.3, 1.0, 1.0),
    (1.0, 0.6, 0.2, 1.0),
    (0.5, 0.9, 1.0, 1.0),
    (1.0, 1.0, 0.5, 1.0),
]
CANOPY_COLORS: list[Color] = [
    (0.05, 0.45, 0.05, 1.0),
    (0.1, 0.55, 0.1, 1.0),
    (0.15, 0.65, 0.15, 1.0),
    (0.05, 0.35, 0.1, 1.0),
]
BUSH_COLORS: list[Color] = [
    (0.1, 0.5, 0.05, 1.0),
    (0.05, 0.4, 0.1, 1.0),
    (0.15, 0.55, 0.05, 1.0),
    (0.1, 0.45, 0.15, 1.0),
]
TRUNK_COLOR: Color = (0.4, 0.25, 0.08, 1.0)
VINE_COLOR: Color = (0.05, 0.4, 0.1, 1.0)
BIRD_COLORS: list[Color] = [
    (1.0, 0.3, 0.1, 1.0),
    (0.2, 0.6, 1.0, 1.0),
    (1.0, 0.8, 0.0, 1.0),
    (0.9, 0.3, 0.9, 1.0),
    (0.0, 0.9, 0.7, 1.0),
]

# ---------------------------------------------------------------------------
# Flower pattern constants (adapted from ascii_flowers.py)
# ---------------------------------------------------------------------------

PETALS: dict[str, list[str]] = {
    'N':  ['|', "'", ','],
    'NE': ['/', '.'],
    'E':  ['-', '~', ')'],
    'SE': ['\\', '.', ','],
    'S':  ['|', '.', ','],
    'SW': ['/', '.', "'"],
    'W':  ['-', '~', '('],
    'NW': ['\\', '.', "'"],
}

CENTERS = ['@', 'o', 'O', '*', '#', '&', '%']

SYMMETRIES: dict[str, list[str]] = {
    'cross':   ['N', 'E', 'S', 'W'],
    'saltire': ['NE', 'SE', 'SW', 'NW'],
    'hex':     ['N', 'NE', 'SE', 'S', 'SW', 'NW'],
    'star':    ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
    'tri':     ['N', 'SW', 'SE'],
    'asym5':   ['N', 'NE', 'E', 'S', 'W'],
}

# Row, col offsets in 3x3 grid (center = 1,1)
POS_3: dict[str, tuple[int, int]] = {
    'NW': (0, 0), 'N': (0, 1), 'NE': (0, 2),
    'W':  (1, 0),               'E':  (1, 2),
    'SW': (2, 0), 'S': (2, 1), 'SE': (2, 2),
}

# Outer ring positions in 5x5 grid (center = 2,2)
POS_5_OUTER: dict[str, tuple[int, int]] = {
    'N':  (0, 2), 'NE': (0, 4), 'E':  (2, 4), 'SE': (4, 4),
    'S':  (4, 2), 'SW': (4, 0), 'W':  (2, 0), 'NW': (0, 0),
}

POS_5_MID_DIAG: dict[str, tuple[int, int]] = {
    'NE': (1, 3), 'SE': (3, 3), 'SW': (3, 1), 'NW': (1, 1),
}

VINE_CHAR_TIMER_MIN = 60
VINE_CHAR_TIMER_MAX = 120

MUSHROOM_CHARS = ["T", "t"]
MUSHROOM_COLORS: list[Color] = [
    (0.82, 0.71, 0.55, 1.0),
    (0.80, 0.20, 0.20, 1.0),
    (0.95, 0.90, 0.80, 1.0),
    (0.50, 0.20, 0.60, 1.0),
]

SNAIL_CHARS = ["@", ">"]
CATERPILLAR_CHARS = ["~", "~", "~", ">"]
CRITTER_COLORS: list[Color] = [
    (1.0, 0.45, 0.1, 1.0),
    (1.0, 0.85, 0.1, 1.0),
    (0.9, 0.20, 0.9, 1.0),
]
CRITTER_SPEED = 0.05

WIND_GUST_CHANCE = 0.30
WIND_GUST_INTERVAL_MIN = 60
WIND_GUST_INTERVAL_MAX = 150
WIND_WAVE_SPEED = 2
WIND_DURATION = 20

FIREFLY_CHARS = [".", "\u00b7"]
FIREFLY_COLORS: list[Color] = [
    (1.0, 0.95, 0.3, 1.0),
    (0.6, 0.90, 0.2, 1.0),
    (1.0, 0.80, 0.1, 1.0),
]
FIREFLY_COUNT_MIN = 8
FIREFLY_COUNT_MAX = 20
FIREFLY_MAX_SPEED = 0.25

RAIN_DROP_COUNT = 30
RAIN_SPEED_MIN = 0.5
RAIN_SPEED_MAX = 1.2
RAIN_COLOR: Color = (0.5, 0.55, 0.7, 0.6)
RAIN_SPLASH_CHAR = "o"
RAIN_SPLASH_DURATION = 6

BUTTERFLY_CHARS = ["*", "~", "+"]
BUTTERFLY_COLORS: list[Color] = [
    (1.0, 0.4, 0.7, 1.0),
    (0.3, 0.6, 1.0, 1.0),
    (1.0, 0.9, 0.2, 1.0),
    (0.7, 0.3, 0.9, 1.0),
]
BUTTERFLY_SPEED = 0.3
BUTTERFLY_COUNT_MIN = 2
BUTTERFLY_COUNT_MAX = 5
BUTTERFLY_FLAP_PERIOD = 6
BUTTERFLY_LAND_MIN = 30
BUTTERFLY_LAND_MAX = 90


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase(IntEnum):
    IDLE = 0
    GROWING = 1
    PERCHING = 2
    FADING = 3
    DONE = 4


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _GrassBlade:
    x: int
    base_y: int
    target_h: int
    current_h: int
    grow_delay: int
    chars: list[str]
    color: Color


@dataclass(slots=True)
class _Flower:
    x: int
    base_y: int
    stem_target: int
    stem_current: int
    bloom_stage: int  # 0=none, 1=bud, 2=open
    bloom_delay: int  # ticks after stem reaches target before bud appears
    color: Color
    size: str = 'tiny'  # 'tiny', '3x3', or '5x5'
    pattern: list[tuple[int, int, str]] | None = None  # (dx, dy, char) offsets
    bloom_tick: int = 0  # tick when bloom_stage became 1


@dataclass(slots=True)
class _Vine:
    path: list[tuple[int, int]]
    current_len: int
    grow_delay: int
    grow_interval: int
    last_grow_tick: int
    color: Color
    cell_chars: list[str] = field(default_factory=list)
    cell_timers: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _Tree:
    x: int
    base_y: int
    trunk_target: int
    trunk_current: int
    canopy_r_target: int
    canopy_r_current: int
    grow_delay: int
    trunk_color: Color
    canopy_color: Color
    branch_y: int  # y of top of trunk (target for birds); may be negative for tall trees
    trunk_width: int = 1  # 2-4 columns wide
    canopy_flowers_spawned: bool = False
    trunk_offsets: list[int] = field(default_factory=list)
    canopy_noise: list[float] = field(default_factory=list)
    canopy_cx: int = 0
    canopy_cache: list[tuple[int, int, str]] | None = None  # cached (x, y, char) for full canopy


@dataclass(slots=True)
class _Bush:
    cx: int
    base_y: int
    w_target: int
    h_target: int
    w_current: int
    h_current: int
    grow_delay: int
    color: Color


@dataclass(slots=True)
class _Bird:
    fx: float
    fy: float
    target_x: int
    target_y: int
    speed: float
    perched: bool
    going_left: bool
    color: Color
    spawn_tick: int


@dataclass(slots=True)
class _Mushroom:
    x: int
    base_y: int
    char: str
    color: Color
    grow_delay: int
    visible: bool = False


@dataclass(slots=True)
class _Critter:
    tree_idx: int
    kind: str  # 'snail' or 'caterpillar'
    color: Color
    fy: float
    target_y: int
    speed: float
    side: int  # -1 or 1
    reached: bool = False


@dataclass(slots=True)
class _Wind:
    active: bool
    direction: int  # -1 or 1
    wave_front_x: float
    start_tick: int
    next_gust_tick: int


@dataclass(slots=True)
class _Firefly:
    fx: float
    fy: float
    color: Color
    char: str
    spawn_delay: int
    vx: float
    vy: float
    alive: bool


@dataclass(slots=True)
class _Leaf:
    spawn_x: int
    spawn_y: int
    ground_y: int
    fy: float
    color: Color
    char_idx: int
    last_char_tick: int
    fall_rate: float
    period: float
    h_amplitude: float
    v_amplitude: float
    spawn_delay: int
    alive: bool
    draw_x: int
    draw_y: int
    state: str  # 'canopy' or 'falling'


@dataclass(slots=True)
class _RainDrop:
    x: int
    fy: float
    speed: float
    char: str
    active: bool


@dataclass(slots=True)
class _RainSplash:
    x: int
    y: int
    birth_tick: int
    duration: int


@dataclass(slots=True)
class _Butterfly:
    fx: float
    fy: float
    target_flower_idx: int
    color: Color
    char_idx: int
    state: str  # 'flying' or 'landed'
    landed_tick: int
    land_duration: int
    sine_offset: float


# ---------------------------------------------------------------------------
# GroveEffect
# ---------------------------------------------------------------------------

class GroveEffect:
    EFFECT_META = {"name": "grove", "description": "A vibrant grove grows from the terminal bottom"}
    destructive = False

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
        self._phase_start = 0
        self._fade_start_tick = -1

        self._grass: list[_GrassBlade] = []
        self._flowers: list[_Flower] = []
        self._vines: list[_Vine] = []
        self._trees: list[_Tree] = []
        self._bushes: list[_Bush] = []
        self._birds: list[_Bird] = []
        self._attached_flowers: list[_Flower] = []
        self._mushrooms: list[_Mushroom] = []
        self._critters: list[_Critter] = []
        self._fireflies: list[_Firefly] = []
        self._leaves: list[_Leaf] = []
        self._rain_drops: list[_RainDrop] = []
        self._rain_splashes: list[_RainSplash] = []
        self._has_rain = False
        self._butterflies: list[_Butterfly] = []
        self._wind = _Wind(
            active=False, direction=1, wave_front_x=0.0, start_tick=0,
            next_gust_tick=self._rng.randint(WIND_GUST_INTERVAL_MIN, WIND_GUST_INTERVAL_MAX),
        )
        # Static vegetation cache: built once when entering PERCHING
        self._static_cells: dict[tuple[int, int], Cell] | None = None


    # -- Protocol callbacks --------------------------------------------------

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
        self._init_scene()
        self._phase = Phase.GROWING
        self._phase_start = self._tick_count

    def _reset_state(self) -> None:
        self._grass = []
        self._flowers = []
        self._vines = []
        self._trees = []
        self._bushes = []
        self._birds = []
        self._attached_flowers = []
        self._mushrooms = []
        self._critters = []
        self._fireflies = []
        self._leaves = []
        self._rain_drops = []
        self._rain_splashes = []
        self._has_rain = False
        self._butterflies = []
        self._wind = _Wind(
            active=False, direction=1, wave_front_x=0.0, start_tick=0,
            next_gust_tick=self._rng.randint(WIND_GUST_INTERVAL_MIN, WIND_GUST_INTERVAL_MAX),
        )
        self._phase_start = 0
        self._fade_start_tick = -1

    def _pick_delay(self) -> int:
        return round(self._rng.uniform(0.75, 1.25) * self._idle_secs * 30)

    def on_resize(self, resize: TTYResize) -> None:
        if self._phase in (Phase.IDLE, Phase.DONE):
            return
        if (resize.width, resize.height) != (self._width, self._height):
            self._handle_resize(resize.width, resize.height)

    def _handle_resize(self, new_w: int, new_h: int) -> None:
        self._width = new_w
        self._height = new_h
        # Invalidate caches on resize
        for tree in self._trees:
            tree.canopy_cache = None
        self._static_cells = None
        # Clamp all flora
        for g in self._grass:
            g.x = max(0, min(new_w - 1, g.x))
            g.base_y = max(0, min(new_h - 1, g.base_y))
        for f in self._flowers:
            f.x = max(0, min(new_w - 1, f.x))
            f.base_y = max(0, min(new_h - 1, f.base_y))
        for f in self._attached_flowers:
            f.x = max(0, min(new_w - 1, f.x))
            f.base_y = max(0, min(new_h - 1, f.base_y))
        for v in self._vines:
            v.path = [
                (max(0, min(new_w - 1, px)), max(0, min(new_h - 1, py)))
                for px, py in v.path
            ]
        for t in self._trees:
            t.x = max(0, min(new_w - 1, t.x))
            t.base_y = max(0, min(new_h - 1, t.base_y))
            t.branch_y = t.base_y - t.trunk_current
            t.canopy_cx = max(0, min(new_w - 1, t.canopy_cx))
        for b in self._bushes:
            b.cx = max(0, min(new_w - 1, b.cx))
            b.base_y = max(0, min(new_h - 1, b.base_y))
        for bird in self._birds:
            bird.fx = max(0.0, min(float(new_w - 1), bird.fx))
            bird.fy = max(0.0, min(float(new_h - 1), bird.fy))
            bird.target_x = max(0, min(new_w - 1, bird.target_x))
            bird.target_y = max(0, min(new_h - 1, bird.target_y))
        for m in self._mushrooms:
            m.x = max(0, min(new_w - 1, m.x))
            m.base_y = max(0, min(new_h - 1, m.base_y))
        for c in self._critters:
            c.fy = max(0.0, min(float(new_h - 1), c.fy))
            c.target_y = max(0, min(new_h - 1, c.target_y))
        for ff in self._fireflies:
            ff.fx = max(0.0, min(float(new_w - 1), ff.fx))
            ff.fy = max(0.0, min(float(new_h - 1), ff.fy))
        for lf in self._leaves:
            lf.spawn_x = max(0, min(new_w - 1, lf.spawn_x))
            lf.ground_y = new_h - 1
        for drop in self._rain_drops:
            drop.x = max(0, min(new_w - 1, drop.x))
        for bf in self._butterflies:
            bf.fx = max(0.0, min(float(new_w - 1), bf.fx))
            bf.fy = max(0.0, min(float(new_h - 1), bf.fy))

    # -- Scene initialization ------------------------------------------------

    def _init_scene(self) -> None:
        w = self._width
        h = self._height
        base_y = h - 1

        # Cap trunk max to terminal height
        trunk_max = min(TREE_TRUNK_MAX, h - 2)

        # Grass blades
        self._grass = []
        grass_cols = sorted(self._rng.sample(range(w), min(w, int(w * GRASS_DENSITY))))
        for x in grass_cols:
            target_h = self._rng.randint(GRASS_MIN_H, min(GRASS_MAX_H, h - 1))
            chars = [self._rng.choice(GRASS_CHARS) for _ in range(target_h)]
            color = self._rng.choice(GRASS_COLORS)
            delay = self._rng.randint(0, 80)
            self._grass.append(_GrassBlade(
                x=x, base_y=base_y, target_h=target_h, current_h=0,
                grow_delay=delay, chars=chars, color=color,
            ))

        # Flowers
        self._flowers = []
        flower_count = max(1, int(w * FLOWER_DENSITY))
        flower_xs = self._rng.sample(range(w), min(w, flower_count))
        for x in flower_xs:
            stem_target = self._rng.randint(FLOWER_STEM_MIN, min(FLOWER_STEM_MAX, h - 1))
            bloom_delay = self._rng.randint(0, 30)
            color = self._rng.choice(FLOWER_COLORS)
            size = self._rng.choices(['tiny', '3x3', '5x5'], weights=[2, 5, 3])[0]
            self._flowers.append(_Flower(
                x=x, base_y=base_y, stem_target=stem_target, stem_current=0,
                bloom_stage=0, bloom_delay=bloom_delay, color=color, size=size,
            ))

        # Trees (grow during GROWING phase)
        self._trees = []
        tree_count = min(TREE_COUNT, max(1, w // 6))
        band = max(1, w // (tree_count + 1))
        for i in range(tree_count):
            tx = band * (i + 1) + self._rng.randint(-band // 3, band // 3)
            tx = max(0, min(w - 1, tx))
            trunk_target = self._rng.randint(TREE_TRUNK_MIN, max(TREE_TRUNK_MIN, trunk_max))
            canopy_r = self._rng.randint(TREE_CANOPY_MIN_R, min(TREE_CANOPY_MAX_R, w // 3))
            canopy_color = self._rng.choice(CANOPY_COLORS)
            trunk_width = self._rng.choices([2, 3, 4], weights=[2, 4, 3])[0]
            # Curvy trunk via random-walk offsets
            trunk_offsets = [0]
            for _ in range(trunk_target - 1):
                drift = self._rng.choices([-1, 0, 1], weights=[1, 3, 1])[0]
                new_off = max(-3, min(3, trunk_offsets[-1] + drift))
                trunk_offsets.append(new_off)
            # Amorphous canopy noise (16 angular sectors)
            canopy_noise = [self._rng.uniform(0.7, 1.1) for _ in range(16)]
            self._trees.append(_Tree(
                x=tx, base_y=base_y, trunk_target=trunk_target, trunk_current=0,
                canopy_r_target=canopy_r, canopy_r_current=0,
                grow_delay=self._rng.randint(0, 20),
                trunk_color=TRUNK_COLOR, canopy_color=canopy_color,
                branch_y=base_y, trunk_width=trunk_width,
                trunk_offsets=trunk_offsets, canopy_noise=canopy_noise,
                canopy_cx=tx,
            ))

        # Bushes
        self._bushes = []
        bush_count = self._rng.randint(*BUSH_COUNT_RANGE)
        for tree in self._trees:
            offset = self._rng.randint(-4, 4)
            bx = max(2, min(w - 3, tree.x + offset))
            w_target = self._rng.randint(5, 11)
            h_target = self._rng.randint(2, 5)
            color = self._rng.choice(BUSH_COLORS)
            delay = self._rng.randint(0, 30)
            self._bushes.append(_Bush(
                cx=bx, base_y=base_y, w_target=w_target, h_target=h_target,
                w_current=0, h_current=0, grow_delay=delay, color=color,
            ))
        # Extra random bushes
        for _ in range(max(0, bush_count - len(self._trees))):
            bx = self._rng.randint(2, max(2, w - 3))
            w_target = self._rng.randint(3, 7)
            h_target = self._rng.randint(2, 4)
            color = self._rng.choice(BUSH_COLORS)
            delay = self._rng.randint(0, 40)
            self._bushes.append(_Bush(
                cx=bx, base_y=base_y, w_target=w_target, h_target=h_target,
                w_current=0, h_current=0, grow_delay=delay, color=color,
            ))

        # Vines — climb trees and drape between adjacent pairs (grow during GROWING)
        self._vines = []
        sorted_trees = sorted(self._trees, key=lambda t: t.x)
        for i in range(len(sorted_trees) - 1):
            path = self._build_vine_path(sorted_trees[i], sorted_trees[i + 1])
            grow_interval = self._rng.randint(3, 7)
            grow_delay = self._rng.randint(10, 50)
            cell_chars = [self._rng.choice(VINE_CHARS) for _ in path]
            cell_timers = [self._rng.randint(VINE_CHAR_TIMER_MIN, VINE_CHAR_TIMER_MAX)
                           for _ in path]
            self._vines.append(_Vine(
                path=path, current_len=0,
                grow_delay=grow_delay, grow_interval=grow_interval,
                last_grow_tick=0, color=VINE_COLOR,
                cell_chars=cell_chars, cell_timers=cell_timers,
            ))

        # Birds (start off-screen, target tree canopy tops)
        self._birds = []
        bird_count = self._rng.randint(*BIRD_COUNT_RANGE)
        for i in range(bird_count):
            tree = self._trees[i % len(self._trees)]
            going_left = self._rng.random() < 0.5
            fx = -2.0 if not going_left else float(w + 2)
            fy = float(self._rng.randint(0, max(0, h // 2)))
            target_x = tree.x
            target_y = max(0, tree.base_y - tree.trunk_target - tree.canopy_r_target // 2)
            color = self._rng.choice(BIRD_COLORS)
            spawn_tick = self._rng.randint(0, 60)
            self._birds.append(_Bird(
                fx=fx, fy=fy, target_x=target_x, target_y=target_y,
                speed=BIRD_SPEED + self._rng.uniform(-0.3, 0.3),
                perched=False, going_left=going_left, color=color,
                spawn_tick=spawn_tick,
            ))

        # Attached flowers (vine/canopy flowers spawned dynamically)
        self._attached_flowers = []

        # Rain (~12% of cycles)
        self._has_rain = self._rng.random() < 0.12
        self._rain_splashes = []
        self._rain_drops = []
        if self._has_rain:
            for _ in range(RAIN_DROP_COUNT):
                self._rain_drops.append(_RainDrop(
                    x=self._rng.randint(0, w - 1),
                    fy=self._rng.uniform(-h, 0),
                    speed=self._rng.uniform(RAIN_SPEED_MIN, RAIN_SPEED_MAX),
                    char="|", active=False,
                ))

        # Mushrooms: 2-5 per tree near trunk base
        self._mushrooms = []
        for tree in self._trees:
            half_w = tree.trunk_width // 2
            count = self._rng.randint(2, 5)
            for _ in range(count):
                sign = -1 if self._rng.random() < 0.5 else 1
                offset = sign * self._rng.randint(1, half_w + 2)
                mx = max(0, min(w - 1, tree.x + offset))
                self._mushrooms.append(_Mushroom(
                    x=mx, base_y=base_y,
                    char=self._rng.choice(MUSHROOM_CHARS),
                    color=self._rng.choice(MUSHROOM_COLORS),
                    grow_delay=self._rng.randint(150, 300),
                ))

        # Crawling critters: 1-2 on random trees
        self._critters = []
        critter_count = self._rng.randint(1, 2)
        critter_idxs = self._rng.sample(range(len(self._trees)), min(critter_count, len(self._trees)))
        for idx in critter_idxs:
            tree = self._trees[idx]
            kind = "snail" if self._rng.random() < 0.5 else "caterpillar"
            lo = int(tree.trunk_target * 0.3)
            hi = int(tree.trunk_target * 0.7)
            target_y = max(0, tree.base_y - self._rng.randint(lo, max(lo, hi)))
            self._critters.append(_Critter(
                tree_idx=idx, kind=kind,
                color=self._rng.choice(CRITTER_COLORS),
                fy=float(base_y), target_y=target_y,
                speed=CRITTER_SPEED,
                side=-1 if self._rng.random() < 0.5 else 1,
            ))

        # Wind state
        self._wind = _Wind(
            active=False, direction=1, wave_front_x=0.0, start_tick=0,
            next_gust_tick=self._rng.randint(WIND_GUST_INTERVAL_MIN, WIND_GUST_INTERVAL_MAX),
        )

        # Fireflies (only if no rain)
        self._fireflies = []
        if not self._has_rain:
            ff_count = self._rng.randint(FIREFLY_COUNT_MIN, FIREFLY_COUNT_MAX)
            for _ in range(ff_count):
                self._fireflies.append(_Firefly(
                    fx=float(self._rng.randint(0, w - 1)),
                    fy=float(base_y - self._rng.randint(0, 3)),
                    color=self._rng.choice(FIREFLY_COLORS),
                    char=self._rng.choice(FIREFLY_CHARS),
                    spawn_delay=self._rng.randint(0, 120),
                    vx=self._rng.uniform(-0.15, 0.15),
                    vy=self._rng.uniform(-0.15, 0.05),
                    alive=True,
                ))

        # Falling leaves — populated lazily when each tree's canopy finishes growing
        self._leaves = []

        # Butterflies (only if no rain)
        self._butterflies = []
        if not self._has_rain:
            bf_count = self._rng.randint(BUTTERFLY_COUNT_MIN, BUTTERFLY_COUNT_MAX)
            for _ in range(bf_count):
                self._butterflies.append(_Butterfly(
                    fx=self._rng.uniform(0, w - 1),
                    fy=self._rng.uniform(0, h // 2),
                    target_flower_idx=-1,
                    color=self._rng.choice(BUTTERFLY_COLORS),
                    char_idx=self._rng.randint(0, len(BUTTERFLY_CHARS) - 1),
                    state="flying",
                    landed_tick=0,
                    land_duration=self._rng.randint(BUTTERFLY_LAND_MIN, BUTTERFLY_LAND_MAX),
                    sine_offset=self._rng.uniform(0, math.pi * 2),
                ))

    def _build_vine_path(self, t1: _Tree, t2: _Tree) -> list[tuple[int, int]]:
        """Build a vine path climbing t1's trunk then draping to t2 with parabolic sag."""
        h = self._height
        w = self._width
        path: list[tuple[int, int]] = []

        # Climb t1's trunk from base to top (screen-capped; vines don't go off-screen)
        y1_top = max(0, t1.base_y - t1.trunk_target)
        for y in range(t1.base_y, y1_top - 1, -1):
            path.append((t1.x, y))

        # Drape from t1's top to t2's top with a parabolic sag
        y2_top = max(0, t2.base_y - t2.trunk_target)
        steps = abs(t2.x - t1.x)
        if steps > 0:
            sag = min(h // 5, 8) + self._rng.randint(0, 3)
            direction = 1 if t2.x > t1.x else -1
            for i in range(1, steps + 1):
                t_frac = i / steps
                y_lerp = y1_top + (y2_top - y1_top) * t_frac
                sag_y = sag * 4 * t_frac * (1 - t_frac)
                y = int(y_lerp + sag_y)
                y = max(0, min(h - 1, y))
                x = max(0, min(w - 1, t1.x + i * direction))
                path.append((x, y))

        return path

    # -- Flower pattern generation -------------------------------------------

    def _generate_flower_pattern(self, flower: _Flower) -> list[tuple[int, int, str]]:
        """Generate (dx, dy, char) offsets for a multi-cell flower pattern."""
        if flower.size == 'tiny':
            ch = self._rng.choice(FLOWER_OPEN)
            return [(0, 0, ch)]

        if flower.size == '3x3':
            sym_name = self._rng.choice(list(SYMMETRIES.keys()))
            center = self._rng.choice(CENTERS)
            offsets: list[tuple[int, int, str]] = [(0, 0, center)]
            for d in SYMMETRIES[sym_name]:
                r, c = POS_3[d]
                dr = r - 1  # center is at (1,1) in 3x3
                dc = c - 1
                ch = self._rng.choice(PETALS[d])
                offsets.append((dc, dr, ch))
            return offsets

        # 5x5
        center = self._rng.choice(CENTERS)
        offsets = [(0, 0, center)]

        # Inner ring (3x3)
        inner_sym = self._rng.choice(list(SYMMETRIES.keys()))
        for d in SYMMETRIES[inner_sym]:
            r, c = POS_3[d]
            dr = (r + 1) - 2  # POS_3 is in 3x3 space, offset +1 to center in 5x5
            dc = (c + 1) - 2
            ch = self._rng.choice(PETALS[d])
            offsets.append((dc, dr, ch))

        # Outer ring
        outer_sym = self._rng.choice(['cross', 'saltire', 'star'])
        for d in SYMMETRIES[outer_sym]:
            r, c = POS_5_OUTER[d]
            dr = r - 2  # center is at (2,2) in 5x5
            dc = c - 2
            ch = self._rng.choice(PETALS[d])
            offsets.append((dc, dr, ch))

        # Fill diagonal midpoints
        for d in ['NE', 'SE', 'SW', 'NW']:
            if d in SYMMETRIES[inner_sym] and d in SYMMETRIES[outer_sym]:
                r, c = POS_5_MID_DIAG[d]
                dr = r - 2
                dc = c - 2
                ch = self._rng.choice(PETALS[d])
                offsets.append((dc, dr, ch))

        return offsets

    # -- Growth ticks --------------------------------------------------------

    def _grow_stems_tick(self) -> None:
        """Grow grass, flower stems, bloom flowers, and grow vines (GROWING phase)."""
        t = self._tick_count
        ph_t = t - self._phase_start

        # Grass
        for g in self._grass:
            if t >= g.grow_delay and g.current_h < g.target_h:
                if (t - g.grow_delay - 1) % 4 == 0:
                    g.current_h += 1

        # Flower stems + blooming
        for f in self._flowers:
            if f.stem_current < f.stem_target:
                if t % 5 == 0:
                    f.stem_current += 1
            elif f.bloom_stage == 0:
                # Stem reached target — start bloom after delay
                if f.bloom_tick == 0:
                    f.bloom_tick = t
                if t - f.bloom_tick >= f.bloom_delay:
                    f.bloom_stage = 1
                    f.bloom_tick = t
            elif f.bloom_stage == 1 and t - f.bloom_tick >= 20:
                f.bloom_stage = 2
                f.pattern = self._generate_flower_pattern(f)

        # Vines
        for v in self._vines:
            if ph_t >= v.grow_delay and v.current_len < len(v.path):
                if ph_t - v.last_grow_tick >= v.grow_interval:
                    old_len = v.current_len
                    v.current_len += 1
                    v.last_grow_tick = ph_t
                    # Chance to spawn a flower on the new vine cell
                    if self._rng.random() < 0.15:
                        px, py = v.path[old_len]
                        color = self._rng.choice(BRIGHT_FLOWER_COLORS)
                        vine_size = self._rng.choices(
                            ['tiny', '3x3'], weights=[3, 2])[0]
                        af = _Flower(
                            x=px, base_y=py, stem_target=0, stem_current=0,
                            bloom_stage=1, bloom_delay=0, color=color,
                            size=vine_size, bloom_tick=t,
                        )
                        self._attached_flowers.append(af)

        # Update vine char timers
        self._update_vine_chars()

    def _grow_trees_bushes_tick(self) -> None:
        """Grow trees and bushes (GROWING phase)."""
        t = self._tick_count
        ph_t = t - self._phase_start
        for tree in self._trees:
            if ph_t < tree.grow_delay:
                continue
            local_t = ph_t - tree.grow_delay
            if tree.trunk_current < tree.trunk_target:
                if local_t % 3 == 0:
                    tree.trunk_current += 1
                    tree.branch_y = tree.base_y - tree.trunk_current
                    if tree.trunk_offsets:
                        tree.canopy_cx = tree.x + tree.trunk_offsets[tree.trunk_current - 1]
            elif tree.canopy_r_current < tree.canopy_r_target:
                trunk_done_t = tree.trunk_target * 3
                canopy_t = local_t - trunk_done_t
                if canopy_t > 0 and canopy_t % 5 == 0:
                    tree.canopy_r_current += 1
            # Spawn canopy flowers and leaves when canopy is fully grown
            if (tree.canopy_r_current == tree.canopy_r_target
                    and tree.canopy_r_current > 0
                    and not tree.canopy_flowers_spawned):
                tree.canopy_flowers_spawned = True
                self._spawn_canopy_flowers(tree)
                self._spawn_canopy_leaves(tree)

        for bush in self._bushes:
            if ph_t < bush.grow_delay:
                continue
            local_t = ph_t - bush.grow_delay
            if local_t % 4 == 0:
                if bush.w_current < bush.w_target:
                    bush.w_current += 1
                if bush.h_current < bush.h_target:
                    bush.h_current += 1

    def _spawn_canopy_flowers(self, tree: _Tree) -> None:
        """Scatter flowers at random positions within a tree's canopy."""
        count = self._rng.randint(3, 6)
        r = tree.canopy_r_current
        center_y = tree.branch_y
        for _ in range(count):
            # Pick a random position within the canopy ellipse
            for _attempt in range(10):
                dx = self._rng.randint(-r, r)
                dy = self._rng.randint(-int(r * 0.7), int(r * 0.7))
                if r > 0 and ((dx / r) ** 2 + (dy / (r * 0.7 + 0.01)) ** 2) <= 1.0:
                    fx = tree.canopy_cx + dx
                    fy = center_y + dy
                    if 0 <= fx < self._width and 0 <= fy < self._height:
                        color = self._rng.choice(BRIGHT_FLOWER_COLORS)
                        size = self._rng.choices(
                            ['tiny', '3x3'], weights=[3, 2])[0]
                        af = _Flower(
                            x=fx, base_y=fy, stem_target=0, stem_current=0,
                            bloom_stage=1, bloom_delay=0, color=color,
                            size=size, bloom_tick=self._tick_count,
                        )
                        self._attached_flowers.append(af)
                        break

    def _spawn_canopy_leaves(self, tree: _Tree) -> None:
        """Spawn falling leaves at the bottom edge of a tree's canopy ellipse."""
        count = self._rng.randint(3, 6)
        r = tree.canopy_r_current
        ry = max(1, int(r * 0.7))
        center_y = tree.branch_y
        for _ in range(count):
            dx = self._rng.randint(-(r - 1), r - 1)
            norm_dx = dx / max(1, r)
            dy = int(ry * math.sqrt(max(0.0, 1.0 - norm_dx * norm_dx)))
            sx = tree.canopy_cx + dx
            sy = center_y + dy
            if 0 <= sx < self._width and 0 <= sy < self._height:
                period = self._rng.uniform(1.5, 4.0)
                self._leaves.append(_Leaf(
                    spawn_x=sx, spawn_y=sy, ground_y=tree.base_y,
                    fy=0.0, color=tree.canopy_color,
                    char_idx=self._rng.randint(0, len(CANOPY_CHARS) - 1),
                    last_char_tick=0,
                    fall_rate=self._rng.uniform(0.08, 0.2),
                    period=period,
                    h_amplitude=self._rng.uniform(0.75, 2.25) * (1 + period * 0.7),
                    v_amplitude=self._rng.uniform(0.3, 0.6) * (1 + period * 0.4),
                    spawn_delay=self._rng.randint(0, 250),
                    alive=True, draw_x=sx, draw_y=sy, state="canopy",
                ))

    def _update_vine_chars(self) -> None:
        """Update vine character timers; swap chars when timer expires."""
        for v in self._vines:
            for i in range(min(v.current_len, len(v.cell_timers))):
                v.cell_timers[i] -= 1
                if v.cell_timers[i] <= 0:
                    v.cell_chars[i] = self._rng.choice(VINE_CHARS)
                    v.cell_timers[i] = self._rng.randint(
                        VINE_CHAR_TIMER_MIN, VINE_CHAR_TIMER_MAX)

    def _bloom_attached_flowers_tick(self) -> None:
        """Progress attached flowers from bud to open."""
        t = self._tick_count
        for f in self._attached_flowers:
            if f.bloom_stage == 1 and t - f.bloom_tick >= 30:
                f.bloom_stage = 2
                f.pattern = self._generate_flower_pattern(f)

    def _get_wind_offset(self, x: int) -> int:
        w = self._wind
        if not w.active:
            return 0
        tail = w.wave_front_x - WIND_DURATION * WIND_WAVE_SPEED * w.direction
        lo = min(w.wave_front_x, tail)
        hi = max(w.wave_front_x, tail)
        return w.direction if lo <= x <= hi else 0

    def _wind_tick(self) -> None:
        ph_t = self._tick_count - self._phase_start
        wind = self._wind
        if wind.active:
            wind.wave_front_x += WIND_WAVE_SPEED * wind.direction
            lo = -WIND_DURATION * WIND_WAVE_SPEED
            hi = self._width + WIND_DURATION * WIND_WAVE_SPEED
            if wind.wave_front_x < lo or wind.wave_front_x > hi:
                wind.active = False
        elif ph_t >= wind.next_gust_tick:
            if self._rng.random() < WIND_GUST_CHANCE:
                wind.active = True
                wind.direction = -1 if self._rng.random() < 0.5 else 1
                wind.wave_front_x = 0.0 if wind.direction > 0 else float(self._width - 1)
                wind.start_tick = ph_t
            wind.next_gust_tick = ph_t + self._rng.randint(WIND_GUST_INTERVAL_MIN, WIND_GUST_INTERVAL_MAX)

    def _mushrooms_tick(self) -> None:
        ph_t = self._tick_count - self._phase_start
        for m in self._mushrooms:
            if not m.visible and ph_t >= m.grow_delay:
                m.visible = True

    def _critters_tick(self) -> None:
        for c in self._critters:
            if c.reached:
                continue
            c.fy -= c.speed
            if c.fy <= c.target_y:
                c.fy = float(c.target_y)
                c.reached = True

    def _fireflies_tick(self) -> None:
        ph_t = self._tick_count - self._phase_start
        for ff in self._fireflies:
            if not ff.alive or ph_t < ff.spawn_delay:
                continue
            ff.vx += self._rng.uniform(-0.04, 0.04)
            ff.vy += self._rng.uniform(-0.04, 0.04)
            speed = math.sqrt(ff.vx * ff.vx + ff.vy * ff.vy)
            if speed > FIREFLY_MAX_SPEED:
                ff.vx = ff.vx / speed * FIREFLY_MAX_SPEED
                ff.vy = ff.vy / speed * FIREFLY_MAX_SPEED
            ff.fx += ff.vx + self._get_wind_offset(round(ff.fx)) * 0.5
            ff.fy += ff.vy
            if ff.fx < 0:
                ff.fx = 0.0
                ff.vx = abs(ff.vx)
            elif ff.fx >= self._width:
                ff.fx = float(self._width - 1)
                ff.vx = -abs(ff.vx)
            if ff.fy < 0:
                ff.alive = False
            elif ff.fy >= self._height:
                ff.fy = float(self._height - 1)
                ff.vy = -abs(ff.vy)

    def _leaves_tick(self) -> None:
        ph_t = self._tick_count - self._phase_start
        t = self._tick_count
        for lf in self._leaves:
            if not lf.alive:
                continue
            if lf.state == "canopy":
                if self._phase == Phase.PERCHING and ph_t >= lf.spawn_delay:
                    lf.state = "falling"
                continue
            lf.fy += lf.fall_rate
            distance = lf.fy
            x_offset = (math.sin(distance / lf.period) * lf.h_amplitude
                        + self._get_wind_offset(round(lf.spawn_x)))
            y_offset = (math.cos(2 * distance / lf.period + math.pi) * lf.v_amplitude
                        + lf.v_amplitude)
            lf.draw_x = round(lf.spawn_x + x_offset)
            lf.draw_y = round(lf.spawn_y + lf.fy + y_offset)
            if t - lf.last_char_tick >= 8:
                lf.char_idx = (lf.char_idx + 1) % len(CANOPY_CHARS)
                lf.last_char_tick = t
            if lf.draw_y >= lf.ground_y - 2:
                lf.alive = False

    def _rain_tick(self) -> None:
        if not self._has_rain:
            return
        w = self._width
        h = self._height
        base_y = h - 1
        t = self._tick_count
        for drop in self._rain_drops:
            if not drop.active:
                drop.active = True
                drop.x = self._rng.randint(0, w - 1)
                drop.fy = self._rng.uniform(-5, 0)
                drop.speed = self._rng.uniform(RAIN_SPEED_MIN, RAIN_SPEED_MAX)
                drop.char = "|" if drop.speed > 0.85 else ":"
            drop.fy += drop.speed
            drop.x += self._get_wind_offset(drop.x)
            drop.x = max(0, min(w - 1, drop.x))
            if drop.fy >= base_y:
                self._rain_splashes.append(_RainSplash(
                    x=drop.x, y=base_y, birth_tick=t, duration=RAIN_SPLASH_DURATION,
                ))
                drop.active = False
        self._rain_splashes = [s for s in self._rain_splashes if t - s.birth_tick < s.duration]

    def _butterflies_tick(self) -> None:
        t = self._tick_count
        w = self._width
        h = self._height
        bloomed = [f for f in self._flowers + self._attached_flowers if f.bloom_stage == 2]
        for bf in self._butterflies:
            if bf.state == "landed":
                if t - bf.landed_tick >= bf.land_duration:
                    bf.state = "flying"
                    bf.target_flower_idx = -1
                continue
            if bf.target_flower_idx < 0 and bloomed:
                bf.target_flower_idx = self._rng.randint(0, len(bloomed) - 1)
            if 0 <= bf.target_flower_idx < len(bloomed):
                target = bloomed[bf.target_flower_idx]
                tx, ty = float(target.x), float(target.base_y)
            else:
                tx, ty = float(w // 2), float(h // 2)
            dx = tx - bf.fx
            dy = ty - bf.fy
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= 1.0:
                bf.fx, bf.fy = tx, ty
                bf.state = "landed"
                bf.landed_tick = t
                bf.land_duration = self._rng.randint(BUTTERFLY_LAND_MIN, BUTTERFLY_LAND_MAX)
                continue
            step = min(BUTTERFLY_SPEED, dist)
            bf.fx += ((dx / dist) * step + self._rng.uniform(-0.2, 0.2)
                      + self._get_wind_offset(round(bf.fx)) * 0.3)
            bf.fy += (dy / dist) * step + math.sin(t / 10 + bf.sine_offset) * 0.15
            bf.fx = max(0.0, min(float(w - 1), bf.fx))
            bf.fy = max(0.0, min(float(h - 1), bf.fy))
            if t % BUTTERFLY_FLAP_PERIOD < BUTTERFLY_FLAP_PERIOD // 2:
                bf.char_idx = (bf.char_idx + 1) % len(BUTTERFLY_CHARS)

    def _perch_tick(self) -> None:
        t = self._tick_count
        ph_t = t - self._phase_start
        # Update bird targets based on current tree branch_y
        for i, bird in enumerate(self._birds):
            tree = self._trees[i % len(self._trees)]
            bird.target_y = max(0, min(self._height - 1, tree.branch_y))

        for bird in self._birds:
            if ph_t < bird.spawn_tick:
                continue
            if bird.perched:
                continue
            dx = bird.target_x - bird.fx
            dy = bird.target_y - bird.fy
            dist_x = abs(dx)
            dist_y = abs(dy)
            if dist_x <= 1.0 and dist_y <= 1.0:
                bird.fx = float(bird.target_x)
                bird.fy = float(bird.target_y)
                bird.perched = True
                continue
            step_x = min(bird.speed, dist_x) * (1 if dx > 0 else -1)
            step_y = min(bird.speed * 0.5, dist_y) * (1 if dy > 0 else -1)
            bird.fx += step_x
            bird.fy += step_y
            bird.going_left = dx < 0
            # Clamp
            bird.fx = max(-2.0, min(float(self._width + 2), bird.fx))
            bird.fy = max(0.0, min(float(self._height - 1), bird.fy))

    # -- Rendering -----------------------------------------------------------

    def _get_fade_alpha(self) -> float:
        if self._phase == Phase.FADING:
            elapsed = self._tick_count - self._fade_start_tick
            return max(0.0, 1.0 - elapsed / FADE_DURATION)
        return 1.0

    def _fade_color(self, c: Color, alpha: float) -> Color:
        return _fade_color_impl(c, alpha)

    def _render_static_vegetation(self, buf: dict[tuple[int, int], Cell],
                                   w: int, h: int, fade_alpha: float) -> None:
        """Render all static vegetation (grass stems, mushrooms, flowers, vines) into buf."""
        def add_cell(x: int, y: int, ch: str, color: Color) -> None:
            if not (0 <= x < w and 0 <= y < h):
                return
            pos = (x, y)
            c = self._fade_color(color, fade_alpha) if fade_alpha < 1.0 else color
            buf[pos] = Cell(character=ch, coordinates=pos, fg=c, bg=None)

        # Grass (wind shifts the top character — only stems are static)
        for g in self._grass:
            for i in range(g.current_h):
                gy = g.base_y - i
                if 0 <= gy < h:
                    is_top = i == g.current_h - 1
                    gx = g.x + (self._get_wind_offset(g.x) if is_top else 0)
                    ch = g.chars[min(i, len(g.chars) - 1)]
                    add_cell(gx, gy, ch, g.color)

        # Mushrooms
        for m in self._mushrooms:
            if m.visible:
                add_cell(m.x, m.base_y, m.char, m.color)

        # Flowers (ground)
        for f in self._flowers:
            stem_color: Color = (0.1, 0.55, 0.1, 1.0)
            for i in range(f.stem_current):
                fy = f.base_y - i
                add_cell(f.x, fy, "|", stem_color)
            if f.stem_current > 0 or f.stem_target == 0:
                head_y = f.base_y - f.stem_current if f.stem_target > 0 else f.base_y
                if f.bloom_stage == 1:
                    add_cell(f.x, head_y, FLOWER_BUD, f.color)
                elif f.bloom_stage == 2 and f.pattern is not None:
                    for dx, dy, ch in f.pattern:
                        add_cell(f.x + dx, head_y + dy, ch, f.color)

        # Vines
        for v in self._vines:
            for i in range(v.current_len):
                if i < len(v.cell_chars):
                    px, py = v.path[i]
                    add_cell(px, py, v.cell_chars[i], v.color)

    def _build_static_cache(self) -> dict[tuple[int, int], Cell]:
        """Build and return the static vegetation cache (fade_alpha=1.0)."""
        buf: dict[tuple[int, int], Cell] = {}
        self._render_static_vegetation(buf, self._width, self._height, 1.0)
        # Trees (trunks + canopies)
        w, h = self._width, self._height
        for tree in self._trees:
            half_w = tree.trunk_width // 2
            for i in range(tree.trunk_current):
                ty = tree.base_y - i
                trunk_off = tree.trunk_offsets[i] if i < len(tree.trunk_offsets) else 0
                for dx in range(-half_w, half_w + 1):
                    tx = tree.x + trunk_off + dx
                    if not (0 <= tx < w and 0 <= ty < h):
                        continue
                    pos = (tx, ty)
                    if dx == 0:
                        buf[pos] = Cell(character=TRUNK_CHAR, coordinates=pos, fg=tree.trunk_color, bg=None)
                    else:
                        ch_idx = (tx * 13 + ty * 7) % len(BARK_CHARS)
                        buf[pos] = Cell(character=BARK_CHARS[ch_idx], coordinates=pos, fg=tree.trunk_color, bg=None)
            if tree.canopy_r_current > 0 and tree.canopy_cache is not None:
                for cx, cy, ch in tree.canopy_cache:
                    if 0 <= cx < w and 0 <= cy < h:
                        pos = (cx, cy)
                        buf[pos] = Cell(character=ch, coordinates=pos, fg=tree.canopy_color, bg=None)
        # Bushes
        for bush in self._bushes:
            if bush.w_current <= 0 or bush.h_current <= 0:
                continue
            wh = bush.w_current
            hh = bush.h_current
            for dy in range(hh):
                for dx in range(-wh, wh + 1):
                    bx = bush.cx + dx
                    by = bush.base_y - dy
                    if not (0 <= bx < w and 0 <= by < h):
                        continue
                    norm_x = abs(dx) / max(1, wh)
                    norm_y = dy / max(1, hh)
                    if norm_x + norm_y <= 1.2:
                        ch_idx = (bx + by * 7) % len(BUSH_CHARS)
                        pos = (bx, by)
                        buf[pos] = Cell(character=BUSH_CHARS[ch_idx], coordinates=pos, fg=bush.color, bg=None)
        # Attached flowers
        for f in self._attached_flowers:
            head_y = f.base_y
            if f.bloom_stage == 1:
                pos = (f.x, head_y)
                if 0 <= f.x < w and 0 <= head_y < h:
                    buf[pos] = Cell(character=FLOWER_BUD, coordinates=pos, fg=f.color, bg=None)
            elif f.bloom_stage == 2 and f.pattern is not None:
                for pdx, pdy, pch in f.pattern:
                    px, py = f.x + pdx, head_y + pdy
                    if 0 <= px < w and 0 <= py < h:
                        pos = (px, py)
                        buf[pos] = Cell(character=pch, coordinates=pos, fg=f.color, bg=None)
        return buf

    def _render(self) -> list[OutputMessage]:
        buf: dict[tuple[int, int], Cell] = {}
        fade_alpha = self._get_fade_alpha()
        w = self._width
        h = self._height

        def add_cell(x: int, y: int, ch: str, color: Color) -> None:
            if not (0 <= x < w and 0 <= y < h):
                return
            pos = (x, y)
            c = self._fade_color(color, fade_alpha) if fade_alpha < 1.0 else color
            buf[pos] = Cell(character=ch, coordinates=pos, fg=c, bg=None)

        # Use static cache during PERCHING (fade_alpha==1.0)
        if self._phase == Phase.PERCHING and self._static_cells is not None:
            buf.update(self._static_cells)
        else:
            # Full render of static vegetation
            self._render_static_vegetation(buf, w, h, fade_alpha)

        # Trees, bushes, attached flowers — skip if using static cache
        _use_static = self._phase == Phase.PERCHING and self._static_cells is not None
        if not _use_static:
            for tree in self._trees:
                # Trunk (multi-width with bark texture, curvy offsets)
                half_w = tree.trunk_width // 2
                for i in range(tree.trunk_current):
                    ty = tree.base_y - i
                    trunk_off = tree.trunk_offsets[i] if i < len(tree.trunk_offsets) else 0
                    for dx in range(-half_w, half_w + 1):
                        tx = tree.x + trunk_off + dx
                        if dx == 0:
                            add_cell(tx, ty, TRUNK_CHAR, tree.trunk_color)
                        else:
                            ch_idx = (tx * 13 + ty * 7) % len(BARK_CHARS)
                            add_cell(tx, ty, BARK_CHARS[ch_idx], tree.trunk_color)
                # Canopy (amorphous shape via per-tree angular noise)
                if tree.canopy_r_current > 0:
                    if tree.canopy_cache is not None and tree.canopy_r_current == tree.canopy_r_target:
                        for cx, cy, ch in tree.canopy_cache:
                            if 0 <= cx < w and 0 <= cy < h:
                                add_cell(cx, cy, ch, tree.canopy_color)
                    else:
                        ccx = tree.canopy_cx
                        center_y = tree.branch_y
                        r = tree.canopy_r_current
                        ry = max(1, int(r * 0.7))
                        n_sectors = len(tree.canopy_noise)
                        canopy_cells: list[tuple[int, int, str]] = []
                        for cy in range(center_y - ry, center_y + ry + 1):
                            for cx in range(ccx - r, ccx + r + 1):
                                if not (0 <= cx < w and 0 <= cy < h):
                                    continue
                                dx_f = (cx - ccx) / max(1, r)
                                dy_f = (cy - center_y) / max(1, ry)
                                dist_sq = dx_f * dx_f + dy_f * dy_f
                                if n_sectors > 0:
                                    angle = math.atan2(dy_f, dx_f)
                                    sector = (angle + math.pi) / (2 * math.pi) * n_sectors
                                    s0 = int(sector) % n_sectors
                                    s1 = (s0 + 1) % n_sectors
                                    frac = sector - int(sector)
                                    noise = tree.canopy_noise[s0] * (1 - frac) + tree.canopy_noise[s1] * frac
                                else:
                                    noise = 1.0
                                threshold = noise * noise
                                if dist_sq <= threshold:
                                    ch_idx = (cx + cy * 31) % len(CANOPY_CHARS)
                                    canopy_cells.append((cx, cy, CANOPY_CHARS[ch_idx]))
                                    add_cell(cx, cy, CANOPY_CHARS[ch_idx], tree.canopy_color)
                                elif dist_sq <= threshold * 1.15:
                                    if ((cx * 17 + cy * 23) % 100) < 50:
                                        ch_idx = (cx + cy * 31) % len(CANOPY_CHARS)
                                        canopy_cells.append((cx, cy, CANOPY_CHARS[ch_idx]))
                                        add_cell(cx, cy, CANOPY_CHARS[ch_idx], tree.canopy_color)
                        if tree.canopy_r_current == tree.canopy_r_target:
                            tree.canopy_cache = canopy_cells

            # Bushes
            for bush in self._bushes:
                if bush.w_current <= 0 or bush.h_current <= 0:
                    continue
                wh = bush.w_current
                hh = bush.h_current
                for dy in range(hh):
                    for dx in range(-wh, wh + 1):
                        bx = bush.cx + dx
                        by = bush.base_y - dy
                        if not (0 <= bx < w and 0 <= by < h):
                            continue
                        norm_x = abs(dx) / max(1, wh)
                        norm_y = dy / max(1, hh)
                        if norm_x + norm_y <= 1.2:
                            ch_idx = (bx + by * 7) % len(BUSH_CHARS)
                            add_cell(bx, by, BUSH_CHARS[ch_idx], bush.color)

        # Falling leaves
        for lf in self._leaves:
            if not lf.alive:
                continue
            if lf.state == "canopy":
                add_cell(lf.spawn_x, lf.spawn_y, CANOPY_CHARS[lf.char_idx], lf.color)
            else:
                add_cell(lf.draw_x, lf.draw_y, CANOPY_CHARS[lf.char_idx], lf.color)

        # Critters (climb tree trunks)
        for c in self._critters:
            if c.tree_idx >= len(self._trees):
                continue
            tree = self._trees[c.tree_idx]
            char_arr = SNAIL_CHARS if c.kind == "snail" else CATERPILLAR_CHARS
            cy = round(c.fy)
            height_idx = tree.base_y - cy
            trunk_off = (tree.trunk_offsets[height_idx]
                         if 0 <= height_idx < len(tree.trunk_offsets) else 0)
            half_w = tree.trunk_width // 2
            cx = tree.x + trunk_off + c.side * (half_w + 1)
            for j, ch in enumerate(char_arr):
                add_cell(cx, cy + j, ch, c.color)

        # Attached flowers (vine/canopy — render on top of trees/vines)
        if not _use_static:
            for f in self._attached_flowers:
                head_y = f.base_y
                if f.bloom_stage == 1:
                    add_cell(f.x, head_y, FLOWER_BUD, f.color)
                elif f.bloom_stage == 2 and f.pattern is not None:
                    for dx, dy, ch in f.pattern:
                        add_cell(f.x + dx, head_y + dy, ch, f.color)

        # Birds (render in front of trees/canopy)
        for bird in self._birds:
            bx = round(bird.fx)
            by = round(bird.fy)
            if not (0 <= by < h):
                continue
            if bird.perched:
                if 0 <= bx < w:
                    add_cell(bx, by, BIRD_PERCH, bird.color)
            else:
                flap = (self._tick_count + bird.spawn_tick) % BIRD_FLAP_PERIOD < BIRD_FLAP_PERIOD // 2
                if bird.going_left:
                    wing = BIRD_L_WINGS[0 if flap else 1]
                    if 0 <= bx < w:
                        add_cell(bx, by, BIRD_L_HEAD, bird.color)
                    if 0 <= bx + 1 < w:
                        add_cell(bx + 1, by, wing, bird.color)
                else:
                    wing = BIRD_R_WINGS[0 if flap else 1]
                    if 0 <= bx - 1 < w:
                        add_cell(bx - 1, by, wing, bird.color)
                    if 0 <= bx < w:
                        add_cell(bx, by, BIRD_R_HEAD, bird.color)

        # Butterflies (not during GROWING)
        if self._phase != Phase.GROWING:
            for bf in self._butterflies:
                add_cell(round(bf.fx), round(bf.fy), BUTTERFLY_CHARS[bf.char_idx], bf.color)

        # Rain
        if self._has_rain:
            for drop in self._rain_drops:
                if drop.active:
                    add_cell(drop.x, round(drop.fy), drop.char, RAIN_COLOR)
            for s in self._rain_splashes:
                add_cell(s.x, s.y, RAIN_SPLASH_CHAR, RAIN_COLOR)

        # Fireflies (not during GROWING)
        if not self._has_rain and self._phase != Phase.GROWING:
            ff_ph_t = self._tick_count - self._phase_start
            for ff in self._fireflies:
                if ff.alive and ff_ph_t >= ff.spawn_delay:
                    add_cell(round(ff.fx), round(ff.fy), ff.char, ff.color)

        all_cells = list(buf.values())
        if not all_cells:
            return []
        return [OutputCells(cells=all_cells)]

    # -- Phase transitions ---------------------------------------------------

    def _update_phase(self) -> None:
        t = self._tick_count
        if self._phase == Phase.GROWING:
            if t - self._phase_start >= GROWING_DURATION:
                self._phase = Phase.PERCHING
                self._phase_start = t
                self._static_cells = self._build_static_cache()
        elif self._phase == Phase.PERCHING:
            if t - self._phase_start >= PERCHING_DURATION:
                self._phase = Phase.FADING
                self._fade_start_tick = t
        elif self._phase == Phase.FADING:
            if self._get_fade_alpha() <= 0.0:
                self._phase = Phase.DONE

    # -- Main tick -----------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def cancel(self) -> None:
        """Begin fading from any active phase."""
        if self._phase in (Phase.GROWING, Phase.PERCHING):
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

        # Dispatch simulation
        if self._phase == Phase.GROWING:
            self._grow_stems_tick()
            self._grow_trees_bushes_tick()
            self._bloom_attached_flowers_tick()
            self._mushrooms_tick()
            if self._has_rain and self._tick_count - self._phase_start >= 200:
                self._rain_tick()
        elif self._phase == Phase.PERCHING:
            self._perch_tick()
            self._update_vine_chars()
            self._bloom_attached_flowers_tick()
            self._wind_tick()
            self._critters_tick()
            self._leaves_tick()
            if self._has_rain:
                self._rain_tick()
            else:
                self._fireflies_tick()
                self._butterflies_tick()
        elif self._phase == Phase.FADING:
            self._leaves_tick()
            if self._has_rain:
                self._rain_tick()

        # Render before phase transition (freeze fix)
        result = self._render()

        self._update_phase()
        return result


if __name__ == "__main__":
    run(GroveEffect())
