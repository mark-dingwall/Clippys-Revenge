#!/usr/bin/env python3
"""Space Invaders effect — dramatic rework with bombardment intro and lane-based aliens.

The top third of the terminal is bombarded for ~5 seconds, then individual 2-row aliens
glide in horizontally from alternating sides in dedicated lane bands, dropping bombs that
blast rubble into the code zone. When ~65% of the code zone is rubbled the effect fades out.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from enum import IntEnum

from clippy.harness import run
from clippy.types import Cell, Color, OutputCells, OutputMessage, PTYUpdate, TTYResize

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Timing
ALIEN_MARCH_TICKS  = 4     # ticks between alien position steps
BOMB_FALL_TICKS    = 2     # ticks per bomb row drop
ANIM_FLIP_TICKS    = 15    # ticks between sprite frame flips (~500ms @30fps)
EXPLOSION_DURATION = 4     # ticks an explosion '*' lingers
BLAST_RADIUS       = 2     # Manhattan-distance rubble scatter on impact
FADE_DURATION      = 80    # ticks for FADING alpha fade-out
BOMB_SPAWN_PROB    = 0.07  # probability per alien per tick to drop a bomb
FLUNG_DURATION     = 6     # ticks a flung character remains visible

RUBBLE_THRESHOLD   = 0.65  # fraction of code zone cells rubbled → FADING
ACTIVE_DURATION    = 1050  # ~35s @30fps — hard cap on ACTIVE phase length

# Bombardment
BOMBARDMENT_DURATION  = 150   # ticks (~5s @30fps)
BOMBARDMENT_BOMB_RATE = 3     # spawn a wave every N ticks
BOMBARDMENT_BOMB_COUNT = 6    # bombs per wave

# Top-zone fade after bombardment
TOP_FADE_DURATION = 40    # ticks to fade top zone bg to 0 after bombardment

# Individual aliens (ACTIVE phase)
N_SPRITE_DESIGNS     = 12    # pre-baked sprite pool
ALIEN_SPAWN_INTERVAL = 12    # ticks before a vacated lane refills
ALIEN_SPEED_OPTIONS  = [1, 2]  # |dx| values assigned at spawn
LANE_STAGGER_TICKS   = 8    # additional delay per lane-index at ACTIVE start

# Zone geometry
TOP_MARGIN          = 1    # blank rows above alien sprites
ALIEN_SPRITE_HEIGHT = 2    # cell rows per sprite (4 pixel rows via half-blocks)
ALIEN_SPRITE_WIDTH  = 5    # characters per sprite row
ALIEN_LANE_GAP      = 1    # blank rows between alien sprite rows

# Sprite
ALIEN_COL_STRIDE   = 9     # sprite width + 4 gap (5+4)
ALIEN_GENOME_BITS  = 12    # bits 0-11 determine 5×4-pixel symmetric sprite
ANIM_MASK_BITS     = 4     # bits to flip for animation frame 1

# Colors
ALIEN_COLORS: list[Color] = [
    (0.0,  1.0,  0.0,  1.0),   # bright green
    (0.1,  0.85, 0.15, 1.0),   # lime green
    (0.0,  0.70, 0.30, 1.0),   # medium green
    (0.2,  0.95, 0.05, 1.0),   # yellow-green
]
BOMB_COLOR:      Color = (1.0, 1.0, 0.0, 1.0)   # yellow
EXPLOSION_COLOR: Color = (1.0, 0.5, 0.0, 1.0)   # orange
RUBBLE_COLOR:    Color = (0.4, 0.4, 0.4, 1.0)   # gray
FLUNG_COLOR:     Color = (1.0, 0.9, 0.5, 1.0)   # warm white-yellow for flung text
BLANK_BG:        Color = (0.0, 0.0, 0.05, 1.0)  # near-black bg for top zone

# Defenders
DEFENDER_SHOT_PROB    = 0.03                         # per-tick fire probability
DEFENDER_SHOT_COLOR: Color = (1.0, 1.0, 1.0, 1.0)  # white
ALIEN_KILL_COLOR: Color    = (0.0, 1.0, 0.4, 1.0)  # vivid green-cyan fireball
ALIEN_KILL_DURATION   = 12                            # ticks
ALIEN_KILL_RADIUS     = 4                             # Manhattan radius of fireball

RUBBLE_CHARS = list("░▒▓#$%&*+~.,`")

# Half-block lookup: (top_pixel, bot_pixel) → character
_HALF_BLOCKS: dict[tuple[int, int], str] = {
    (0, 0): " ",
    (1, 0): "▀",
    (0, 1): "▄",
    (1, 1): "█",
}


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase(IntEnum):
    IDLE        = 0
    BOMBARDMENT = 1
    ACTIVE      = 2
    FADING      = 3
    DONE        = 4


# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _Bomb:
    x: int
    y: int


@dataclass(slots=True)
class _BombardBomb:
    x: int
    y: int
    dx: int    # 0 = straight down, +1 = diagonal right, -1 = diagonal left
    det_y: int # target detonation row


@dataclass(slots=True)
class _Explosion:
    x: int
    y: int
    born_tick: int


@dataclass(slots=True)
class _Flung:
    x: int
    y: int
    ch: str
    dx: int        # x velocity (cells per tick)
    dy: int        # y velocity (cells per tick)
    born_tick: int


@dataclass(slots=True)
class _Alien:
    lane: int        # which horizontal lane (0-based)
    x: int           # left edge of sprite
    dx: int          # ±1 or ±2 per march step
    sprite_idx: int  # index into self._sprite_designs
    color: Color     # one of ALIEN_COLORS
    anim_frame: int  # 0 or 1
    anim_timer: int  # per-alien anim tick counter


@dataclass(slots=True)
class _DefenderShot:
    x: int
    y: int


@dataclass(slots=True)
class _AlienKill:
    x: int
    y: int
    born_tick: int


# ---------------------------------------------------------------------------
# Sprite generation
# ---------------------------------------------------------------------------

def _make_sprite(genome: int) -> list[str]:
    """Generate a 5-char × 2-row sprite from a 12-bit genome.

    The 12-bit genome encodes a 5×4 pixel bitmap (5 columns × 4 pixel rows).
    Column offsets [0, 4, 8, 4, 0] provide left-right symmetry.
    Pairs of pixel rows are packed into cell rows using Unicode half-blocks.
    """
    K = 4  # number of pixel rows
    col_offsets = [0, K, 2 * K, K, 0]
    pixels = [
        [(genome >> (col_offsets[x] + y)) & 1 for x in range(5)]
        for y in range(K)
    ]
    rows = []
    for cell_y in range(K // 2):  # 2 cell rows from 4 pixel rows
        top_y = cell_y * 2
        bot_y = cell_y * 2 + 1
        rows.append("".join(
            _HALF_BLOCKS[(pixels[top_y][x], pixels[bot_y][x])]
            for x in range(5)
        ))
    return rows


# ---------------------------------------------------------------------------
# InvadersEffect
# ---------------------------------------------------------------------------

class InvadersEffect:
    EFFECT_META = {
        "name": "invaders",
        "description": "Alien invaders blast your code to rubble",
    }
    destructive = False

    def __init__(self, seed: int | None = None, idle_secs: float | None = None) -> None:
        self._rng = random.Random(seed)
        if idle_secs is None:
            idle_secs = float(os.environ.get("CLIPPY_INTERVAL", "300"))
        self._idle_secs = idle_secs
        self._phase = Phase.IDLE
        self._tick_count = 0
        self._idle_until = -1

        # Terminal dimensions
        self._width = 0
        self._height = 0

        # Zone geometry
        self._top_zone_height = 0   # rows reserved for alien zone
        self._num_lanes = 0         # how many alien lanes fit in top zone
        self._code_zone_start = 0   # first code-zone row
        self._code_zone_cells = 0   # total cells (for threshold)

        # Sprite pool: [design_idx][frame] = list[str]
        self._sprite_designs: list[list[list[str]]] = []

        # Individual aliens (ACTIVE phase)
        self._aliens: list[_Alien] = []
        self._lane_last_exit: list[int] = []  # tick when each lane last became free
        self._march_timer = 0

        # Bombardment (BOMBARDMENT phase)
        self._bombard_bombs: list[_BombardBomb] = []
        self._bombardment_start = 0
        self._top_fade_start = 0

        # Regular bombs / explosions (ACTIVE phase)
        self._bombs: list[_Bomb] = []
        self._bomb_timer = 0
        self._explosions: list[_Explosion] = []

        # Rubble
        self._rubble: dict[tuple[int, int], str] = {}
        self._rubble_count = 0
        self._bombard_rubble: dict[tuple[int, int], str] = {}

        # PTY cell content (for mid-screen bomb detonation)
        self._pty_cells: dict[tuple[int, int], str] = {}

        # Flung text debris
        self._flung: list[_Flung] = []

        # Defenders
        self._defender_shots: list[_DefenderShot] = []
        self._alien_kills: list[_AlienKill] = []

        # Fade
        self._fade_start_tick = 0

        # Active-phase duration cap
        self._active_start_tick = 0
        # Cached opaque black top zone cells (built once when top_alpha reaches 1.0)
        self._top_zone_cache: list[Cell] | None = None

    # -- Zone geometry --------------------------------------------------------

    def _compute_zones(self, w: int, h: int) -> None:
        self._top_zone_height = max(4, h // 3)
        self._num_lanes = (self._top_zone_height - TOP_MARGIN) // (ALIEN_SPRITE_HEIGHT + ALIEN_LANE_GAP)
        self._code_zone_start = self._top_zone_height
        self._code_zone_cells = w * max(0, h - self._top_zone_height)

    # -- Sprite generation ----------------------------------------------------

    def _gen_sprite_design(self) -> list[list[str]]:
        """Return two animation frames for one sprite design."""
        genome = self._rng.getrandbits(ALIEN_GENOME_BITS)
        mask = 0
        for pos in self._rng.sample(range(ALIEN_GENOME_BITS), ANIM_MASK_BITS):
            mask |= (1 << pos)
        return [_make_sprite(genome), _make_sprite(genome ^ mask)]

    def _gen_sprite_designs(self) -> None:
        self._sprite_designs = [
            self._gen_sprite_design() for _ in range(N_SPRITE_DESIGNS)
        ]

    # -- Lane helpers ---------------------------------------------------------

    def _lane_y(self, lane: int) -> int:
        return TOP_MARGIN + lane * (ALIEN_SPRITE_HEIGHT + ALIEN_LANE_GAP)

    # -- Protocol callbacks ---------------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        w, h = update.size
        if self._phase == Phase.IDLE:
            self._width, self._height = w, h
            self._compute_zones(w, h)
            if self._idle_until == -1:
                self._idle_until = self._tick_count + self._pick_delay()
        elif (w, h) != (self._width, self._height):
            self._handle_resize(w, h)
        # Always track PTY cell content for mid-screen bomb detonation
        self._pty_cells = {
            (c.coordinates[0], c.coordinates[1]): c.character
            for c in update.cells
            if c.character != " "
        }

    def on_resize(self, resize: TTYResize) -> None:
        if self._phase in (Phase.IDLE, Phase.DONE):
            return
        if (resize.width, resize.height) != (self._width, self._height):
            self._handle_resize(resize.width, resize.height)

    def _handle_resize(self, new_w: int, new_h: int) -> None:
        self._width, self._height = new_w, new_h
        self._top_zone_cache = None
        self._compute_zones(new_w, new_h)
        new_num_lanes = self._num_lanes

        # Extend or trim lane_last_exit list
        if new_num_lanes > len(self._lane_last_exit):
            self._lane_last_exit.extend(
                [self._tick_count] * (new_num_lanes - len(self._lane_last_exit))
            )
        else:
            self._lane_last_exit = self._lane_last_exit[:new_num_lanes]

        # Remove OOB aliens, recording exit time for their lanes
        new_aliens = []
        for alien in self._aliens:
            if alien.lane < new_num_lanes and 0 <= self._lane_y(alien.lane) < new_h:
                new_aliens.append(alien)
            else:
                lane = alien.lane
                if lane < len(self._lane_last_exit):
                    self._lane_last_exit[lane] = self._tick_count
        self._aliens = new_aliens

        # Remove OOB bombardment bombs
        self._bombard_bombs = [
            b for b in self._bombard_bombs
            if b.y < new_h
        ]

        # Prune OOB rubble, bombs, and flung chars
        self._bombard_rubble = {
            (x, y): ch
            for (x, y), ch in self._bombard_rubble.items()
            if 0 <= x < new_w and 0 <= y < new_h
        }
        self._rubble = {
            (x, y): ch
            for (x, y), ch in self._rubble.items()
            if 0 <= x < new_w and self._code_zone_start <= y < new_h
        }
        self._rubble_count = len(self._rubble)
        self._bombs = [
            b for b in self._bombs
            if 0 <= b.x < new_w and 0 <= b.y < new_h
        ]
        self._flung = [
            f for f in self._flung
            if 0 <= f.x < new_w and 0 <= f.y < new_h
        ]
        self._defender_shots = [
            s for s in self._defender_shots
            if 0 <= s.x < new_w and 0 <= s.y < new_h
        ]
        self._alien_kills = [
            k for k in self._alien_kills
            if 0 <= k.x < new_w and 0 <= k.y < new_h
        ]

    # -- Scheduling -----------------------------------------------------------

    def _start_effect(self) -> None:
        self._gen_sprite_designs()
        self._lane_last_exit = [0] * self._num_lanes
        self._bombardment_start = self._tick_count
        self._phase = Phase.BOMBARDMENT

    def _reset_state(self) -> None:
        self._bombard_bombs = []
        self._bombs = []
        self._bomb_timer = 0
        self._explosions = []
        self._rubble = {}
        self._rubble_count = 0
        self._bombard_rubble = {}
        self._pty_cells = {}
        self._flung = []
        self._defender_shots = []
        self._alien_kills = []
        self._aliens = []
        self._lane_last_exit = []
        self._march_timer = 0
        self._fade_start_tick = 0
        self._top_fade_start = 0

    def _pick_delay(self) -> int:
        return round(self._rng.uniform(0.75, 1.25) * self._idle_secs * 30)

    # -- Phase helpers --------------------------------------------------------

    def _start_fading(self) -> None:
        self._phase = Phase.FADING
        self._fade_start_tick = self._tick_count

    def _check_phase(self) -> None:
        if self._phase != Phase.ACTIVE:
            return
        if self._tick_count - self._active_start_tick >= ACTIVE_DURATION:
            self._start_fading()
            return
        if self._code_zone_cells > 0:
            if self._rubble_count / self._code_zone_cells >= RUBBLE_THRESHOLD:
                self._start_fading()

    def _fade_alpha(self) -> float:
        if self._phase != Phase.FADING:
            return 1.0
        return max(0.0, 1.0 - (self._tick_count - self._fade_start_tick) / FADE_DURATION)

    def _top_zone_alpha(self) -> float:
        """Alpha for the top zone black bg — fades IN after bombardment ends.

        Returns 0.0 during bombardment (terminal visible), then ramps
        from 0→1 over TOP_FADE_DURATION ticks so the entire top zone
        darkens to opaque black before aliens fly in.
        """
        if self._phase == Phase.BOMBARDMENT:
            return 0.0
        elapsed = self._tick_count - self._top_fade_start
        return min(1.0, elapsed / TOP_FADE_DURATION)

    def _tint(self, color: Color, alpha: float) -> Color:
        """Darken a color toward black while preserving alpha.

        This keeps the cell fully opaque so tattoy doesn't blend it with
        the live terminal content underneath the overlay.
        """
        return (color[0] * alpha, color[1] * alpha, color[2] * alpha, color[3])

    # -- Bombardment simulation -----------------------------------------------

    def _do_bombardment(self) -> None:
        # Spawn a wave every BOMBARDMENT_BOMB_RATE ticks
        if self._tick_count % BOMBARDMENT_BOMB_RATE == 0:
            half = BOMBARDMENT_BOMB_COUNT // 2
            quarter = BOMBARDMENT_BOMB_COUNT // 4
            top = max(1, self._top_zone_height)
            for _ in range(half):
                x = self._rng.randint(0, self._width - 1)
                det_y = self._rng.randint(0, top - 1)
                self._bombard_bombs.append(_BombardBomb(x=x, y=-1, dx=0, det_y=det_y))
            for _ in range(quarter):
                x = self._rng.randint(0, self._width - 1)
                det_y = self._rng.randint(0, top - 1)
                self._bombard_bombs.append(_BombardBomb(x=x, y=-1, dx=1, det_y=det_y))
            for _ in range(quarter):
                x = self._rng.randint(0, self._width - 1)
                det_y = self._rng.randint(0, top - 1)
                self._bombard_bombs.append(_BombardBomb(x=x, y=-1, dx=-1, det_y=det_y))

        # Move bombs every BOMB_FALL_TICKS
        if self._bomb_timer >= BOMB_FALL_TICKS:
            self._bomb_timer = 0
            still_alive: list[_BombardBomb] = []
            for bomb in self._bombard_bombs:
                bomb.x += bomb.dx
                bomb.y += 1
                if bomb.y >= bomb.det_y:
                    # Detonate at target row — scatter rubble and create explosion
                    ex = max(0, min(bomb.x, self._width - 1))
                    ey = max(0, min(bomb.y, self._top_zone_height - 1))
                    self._detonate(ex, ey, self._bombard_rubble, 0, self._height, fling=True)
                elif bomb.x < -1 or bomb.x >= self._width + 1:
                    pass  # exited viewport without hitting target — discard silently
                else:
                    still_alive.append(bomb)
            self._bombard_bombs = still_alive

    # -- Active-phase simulation ----------------------------------------------

    def _spawn_alien(self, lane: int) -> None:
        entering_from_left = self._rng.random() < 0.5
        speed = self._rng.choice(ALIEN_SPEED_OPTIONS)
        if entering_from_left:
            dx = speed
            x = -ALIEN_SPRITE_WIDTH
        else:
            dx = -speed
            x = self._width
        color = self._rng.choice(ALIEN_COLORS)
        sprite_idx = self._rng.randrange(len(self._sprite_designs))
        self._aliens.append(_Alien(
            lane=lane, x=x, dx=dx,
            sprite_idx=sprite_idx, color=color,
            anim_frame=0, anim_timer=0,
        ))

    def _do_aliens(self) -> None:
        # Spawn check: refill lanes that have been empty long enough
        occupied_lanes = {a.lane for a in self._aliens}
        for lane in range(self._num_lanes):
            if lane not in occupied_lanes:
                if self._tick_count - self._lane_last_exit[lane] >= ALIEN_SPAWN_INTERVAL:
                    self._spawn_alien(lane)

        # Move aliens every ALIEN_MARCH_TICKS
        if self._march_timer >= ALIEN_MARCH_TICKS:
            self._march_timer = 0
            still_alive: list[_Alien] = []
            for alien in self._aliens:
                alien.x += alien.dx
                exited = (alien.x >= self._width + ALIEN_SPRITE_WIDTH
                          or alien.x < -ALIEN_SPRITE_WIDTH)
                if exited:
                    self._lane_last_exit[alien.lane] = self._tick_count
                else:
                    still_alive.append(alien)
            self._aliens = still_alive

        # Bomb drop: each alien has a chance each tick
        for alien in self._aliens:
            if self._rng.random() < BOMB_SPAWN_PROB:
                bx = alien.x + ALIEN_SPRITE_WIDTH // 2
                by = self._lane_y(alien.lane) + ALIEN_SPRITE_HEIGHT
                if 0 <= bx < self._width and 0 <= by < self._height:
                    self._bombs.append(_Bomb(x=bx, y=by))

        # Per-alien animation
        for alien in self._aliens:
            alien.anim_timer += 1
            if alien.anim_timer >= ANIM_FLIP_TICKS:
                alien.anim_timer = 0
                alien.anim_frame ^= 1

    def _do_bomb_fall(self) -> None:
        self._bomb_timer = 0
        still_falling: list[_Bomb] = []
        for bomb in self._bombs:
            bomb.y += 1
            if bomb.y >= self._code_zone_start:
                if (bomb.x, bomb.y) in self._pty_cells:
                    self._detonate(bomb.x, bomb.y, self._rubble,
                                   self._code_zone_start, self._height, fling=True)
                    continue
                if bomb.y >= self._height - 1:
                    self._detonate(bomb.x, bomb.y, self._rubble,
                                   self._code_zone_start, self._height, fling=True)
                    continue
            still_falling.append(bomb)
        self._bombs = still_falling

    def _detonate(
        self,
        cx: int,
        cy: int,
        rubble_dict: dict[tuple[int, int], str],
        y_min: int,
        y_max: int,
        fling: bool = False,
    ) -> None:
        """Scatter rubble in Manhattan radius around (cx, cy) into rubble_dict.

        y_min/y_max bound which rows are eligible. If fling=True, nearby PTY
        characters are ejected as _Flung debris (active-phase behaviour).
        An explosion marker is always created at the impact point.
        """
        flung_candidates: list[tuple[int, int, str]] = []
        for dy in range(-BLAST_RADIUS, BLAST_RADIUS + 1):
            for dx in range(-BLAST_RADIUS, BLAST_RADIUS + 1):
                if abs(dx) + abs(dy) > BLAST_RADIUS:
                    continue
                rx, ry = cx + dx, cy + dy
                if not (0 <= rx < self._width):
                    continue
                if not (y_min <= ry < y_max):
                    continue
                if (rx, ry) not in rubble_dict:
                    rubble_dict[(rx, ry)] = self._rng.choice(RUBBLE_CHARS)
                    if rubble_dict is self._rubble:
                        self._rubble_count += 1
                if fling:
                    ch = self._pty_cells.pop((rx, ry), None)
                    if ch is not None:
                        flung_candidates.append((rx, ry, ch))
        self._explosions.append(_Explosion(x=cx, y=cy, born_tick=self._tick_count))
        if fling:
            for fx, fy, fch in flung_candidates[:4]:
                fdx = self._rng.choice([-2, -1, 1, 2])
                fdy = self._rng.choice([-1, 0, 1])
                self._flung.append(_Flung(
                    x=fx, y=fy, ch=fch, dx=fdx, dy=fdy, born_tick=self._tick_count,
                ))

    def _do_defender_shots(self) -> None:
        # Spawn one shot per tick with low probability
        if self._aliens and self._rng.random() < DEFENDER_SHOT_PROB:
            x = self._rng.randint(0, self._width - 1)
            self._defender_shots.append(_DefenderShot(x=x, y=self._height - 1))

        # Move shots upward; check alien hits
        killed_aliens: set[int] = set()
        still_alive: list[_DefenderShot] = []
        for shot in self._defender_shots:
            shot.y -= 1
            if shot.y < 0:
                continue  # exited top of screen
            hit = False
            for i, alien in enumerate(self._aliens):
                lane_y = self._lane_y(alien.lane)
                if (lane_y <= shot.y < lane_y + ALIEN_SPRITE_HEIGHT
                        and alien.x <= shot.x < alien.x + ALIEN_SPRITE_WIDTH):
                    cx = alien.x + ALIEN_SPRITE_WIDTH // 2
                    cy = lane_y + ALIEN_SPRITE_HEIGHT // 2
                    self._alien_kills.append(_AlienKill(x=cx, y=cy, born_tick=self._tick_count))
                    self._lane_last_exit[alien.lane] = self._tick_count
                    killed_aliens.add(i)
                    hit = True
                    break
            if not hit:
                still_alive.append(shot)
        if killed_aliens:
            self._aliens = [a for i, a in enumerate(self._aliens) if i not in killed_aliens]
        self._defender_shots = still_alive

    # -- Rendering ------------------------------------------------------------

    def _render_bombardment(self) -> list[OutputMessage]:
        cells: list[Cell] = []

        # Bombardment rubble — overlay on live terminal (terminal text
        # is visible between rubble, giving the effect of being bombed)
        for (rx, ry), ch in self._bombard_rubble.items():
            cells.append(Cell(character=ch, coordinates=(rx, ry), fg=RUBBLE_COLOR, bg=None))

        # Bombardment bombs
        for bomb in self._bombard_bombs:
            if 0 <= bomb.x < self._width and 0 <= bomb.y < self._top_zone_height:
                if bomb.dx < 0:
                    ch = "/"
                elif bomb.dx > 0:
                    ch = "\\"
                else:
                    ch = "|"
                cells.append(Cell(character=ch, coordinates=(bomb.x, bomb.y), fg=BOMB_COLOR, bg=None))

        # Explosions (expire old ones)
        live_explosions: list[_Explosion] = []
        for exp in self._explosions:
            age = self._tick_count - exp.born_tick
            if age >= EXPLOSION_DURATION:
                continue
            live_explosions.append(exp)
            if 0 <= exp.x < self._width and 0 <= exp.y < self._height:
                cells.append(Cell(character="*", coordinates=(exp.x, exp.y), fg=EXPLOSION_COLOR, bg=None))
        self._explosions = live_explosions

        # Flung text debris
        live_flung: list[_Flung] = []
        for f in self._flung:
            age = self._tick_count - f.born_tick
            if age >= FLUNG_DURATION:
                continue
            f.x += f.dx
            f.y += f.dy
            live_flung.append(f)
            if 0 <= f.x < self._width and 0 <= f.y < self._height:
                cells.append(Cell(character=f.ch, coordinates=(f.x, f.y), fg=FLUNG_COLOR, bg=None))
        self._flung = live_flung

        return [OutputCells(cells=cells)]

    def _render_active(self) -> list[OutputMessage]:
        cells: list[Cell] = []
        alpha = self._fade_alpha()
        top_alpha = self._top_zone_alpha()

        def add(cell: Cell) -> None:
            cells.append(cell)

        # 1. Top zone fade-in: after bombardment, gradually darken the entire
        #    top zone to opaque black so aliens have a clean area to fly in.
        #    top_alpha ramps 0→1: at 0 the terminal is fully visible, at 1
        #    it's completely hidden behind opaque black.
        if top_alpha < 1.0:
            # Still fading — cover entire top zone with increasingly opaque bg
            # while bombardment rubble darkens and disappears.
            bg_col: Color = (0.0, 0.0, 0.0, top_alpha)
            fade_factor = 1.0 - top_alpha
            rubble_fg = self._tint(RUBBLE_COLOR, fade_factor * alpha)
            for ty in range(self._top_zone_height):
                for tx in range(self._width):
                    pos = (tx, ty)
                    if pos in self._bombard_rubble:
                        add(Cell(character=self._bombard_rubble[pos],
                                 coordinates=pos, fg=rubble_fg, bg=bg_col))
                    else:
                        add(Cell(character=" ", coordinates=pos, fg=None, bg=bg_col))
            # Bombardment rubble below top zone also darkens
            for (rx, ry), ch in self._bombard_rubble.items():
                if ry >= self._top_zone_height:
                    add(Cell(character=ch, coordinates=(rx, ry),
                             fg=rubble_fg, bg=(0.0, 0.0, 0.0, top_alpha)))
        elif self._bombard_rubble:
            # Fade complete — fully opaque black, clear bombardment rubble
            _OPAQUE_BLACK: Color = (0.0, 0.0, 0.0, 1.0)
            self._top_zone_cache = [
                Cell(character=" ", coordinates=(tx, ty), fg=None, bg=_OPAQUE_BLACK)
                for ty in range(self._top_zone_height)
                for tx in range(self._width)
            ]
            cells.extend(self._top_zone_cache)
            self._bombard_rubble = {}
        elif self._top_zone_cache is not None:
            # Reuse cached opaque black top zone
            cells.extend(self._top_zone_cache)

        # 2. Aliens
        for alien in self._aliens:
            alien_fg = self._tint(alien.color, alpha)
            sprite_rows = self._sprite_designs[alien.sprite_idx][alien.anim_frame]
            lane_y = self._lane_y(alien.lane)
            for row_idx, row_str in enumerate(sprite_rows):
                cy = lane_y + row_idx
                if not (0 <= cy < self._top_zone_height):
                    continue
                for char_idx, ch in enumerate(row_str):
                    if ch == " ":
                        continue
                    cx = alien.x + char_idx
                    if not (0 <= cx < self._width):
                        continue
                    add(Cell(character=ch, coordinates=(cx, cy), fg=alien_fg, bg=None))

        # 3. Bombs
        bomb_fg = self._tint(BOMB_COLOR, alpha)
        for bomb in self._bombs:
            if 0 <= bomb.x < self._width and 0 <= bomb.y < self._height:
                add(Cell(character="|", coordinates=(bomb.x, bomb.y), fg=bomb_fg, bg=None))

        # 4. Explosions (expire old ones)
        live_explosions: list[_Explosion] = []
        explosion_fg = self._tint(EXPLOSION_COLOR, alpha)
        for exp in self._explosions:
            age = self._tick_count - exp.born_tick
            if age >= EXPLOSION_DURATION:
                continue
            live_explosions.append(exp)
            if 0 <= exp.x < self._width and 0 <= exp.y < self._height:
                add(Cell(character="*", coordinates=(exp.x, exp.y), fg=explosion_fg, bg=None))
        self._explosions = live_explosions

        # 5. Rubble (static — always emitted at same positions)
        _OPAQUE_BLACK: Color = (0.0, 0.0, 0.0, 1.0)
        rubble_fg = self._tint(RUBBLE_COLOR, alpha)
        for (rx, ry), ch in self._rubble.items():
            cells.append(Cell(character=ch, coordinates=(rx, ry), fg=rubble_fg, bg=_OPAQUE_BLACK))

        # 6. Flung text debris
        live_flung: list[_Flung] = []
        flung_fg = self._tint(FLUNG_COLOR, alpha)
        for f in self._flung:
            age = self._tick_count - f.born_tick
            if age >= FLUNG_DURATION:
                continue
            f.x += f.dx
            f.y += f.dy
            live_flung.append(f)
            if 0 <= f.x < self._width and 0 <= f.y < self._height:
                add(Cell(character=f.ch, coordinates=(f.x, f.y), fg=flung_fg, bg=None))
        self._flung = live_flung

        # 7. Defender shots (white ^ characters)
        defender_fg = self._tint(DEFENDER_SHOT_COLOR, alpha)
        for shot in self._defender_shots:
            if 0 <= shot.x < self._width and 0 <= shot.y < self._height:
                add(Cell(character="^", coordinates=(shot.x, shot.y), fg=defender_fg, bg=None))

        # 8. Alien kill fireballs (green * cluster, shrinks over time)
        live_kills: list[_AlienKill] = []
        for kill in self._alien_kills:
            age = self._tick_count - kill.born_tick
            if age >= ALIEN_KILL_DURATION:
                continue
            live_kills.append(kill)
            intensity = 1.0 - age / ALIEN_KILL_DURATION
            kill_fg = self._tint(ALIEN_KILL_COLOR, intensity * alpha)
            radius = max(0, ALIEN_KILL_RADIUS - age // 2)
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if abs(dx) + abs(dy) <= radius:
                        cx, cy = kill.x + dx, kill.y + dy
                        if 0 <= cx < self._width and 0 <= cy < self._height:
                            add(Cell(character="*", coordinates=(cx, cy), fg=kill_fg, bg=None))
        self._alien_kills = live_kills

        return [OutputCells(cells=cells)]

    # -- Main tick ------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def cancel(self) -> None:
        """Begin fading from any active phase."""
        if self._phase in (Phase.BOMBARDMENT, Phase.ACTIVE):
            self._start_fading()

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

        if self._phase == Phase.BOMBARDMENT:
            self._bomb_timer += 1
            self._do_bombardment()
            if self._tick_count - self._bombardment_start >= BOMBARDMENT_DURATION:
                self._phase = Phase.ACTIVE
                self._top_fade_start = self._tick_count
                self._active_start_tick = self._tick_count
                # Stagger alien spawning per lane (lane 0 first, each subsequent lane waits more)
                self._lane_last_exit = [
                    self._tick_count - ALIEN_SPAWN_INTERVAL + lane * LANE_STAGGER_TICKS
                    for lane in range(self._num_lanes)
                ]
                self._bomb_timer = 0
                self._march_timer = 0
            return self._render_bombardment()

        elif self._phase == Phase.ACTIVE:
            self._march_timer += 1
            self._bomb_timer += 1
            self._do_aliens()
            self._do_defender_shots()
            if self._bomb_timer >= BOMB_FALL_TICKS:
                self._do_bomb_fall()
            self._check_phase()
            return self._render_active()

        elif self._phase == Phase.FADING:
            if self._fade_alpha() <= 0.0:
                result = self._render_active()
                self._phase = Phase.DONE
                return result
            return self._render_active()

        return []


if __name__ == "__main__":
    run(InvadersEffect())
