#!/usr/bin/env python3
"""Paperclip maximizer effect — exponentially replicates paperclips by consuming terminal content.

True to the AI thought experiment, it reads terminal content and exponentially
replicates paperclip shapes by consuming characters as raw material. Features
wave-based propagation from a screen edge, mixed clip sizes, random fill of
empty space, and an earth phase where the globe itself gets consumed.
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

# Timing
SEEDING_DURATION = 30      # ticks (~1s @30fps)
FADE_DURATION = 60         # ticks (~2s @30fps)
FLASH_DURATION = 4         # ticks per consumed-char flash
EARTH_TRANSITION_DURATION = 60  # ticks (~2s @30fps)

# Growth
GROWTH_RATE_BASE = 1.0     # initial clips per tick
GROWTH_DOUBLING_TICKS = 60 # rate doubles every N ticks
GROWTH_RATE_CAP = 50.0     # max clips per tick

# Wave propagation
WAVE_SPEED_BASE = 0.4      # initial expansion rate (cells/tick)
WAVE_SPEED_MAX = 1.8       # max expansion rate
WAVE_ACCEL = 0.005          # acceleration per tick
CELL_ASPECT_Y = 2.0         # terminal chars are ~2x tall as wide; scale dy up

# Target count
TARGET_PAPERCLIPS = 999_900_000_000_000

# Tier thresholds
TIER1_THRESHOLD = 5
TIER2_THRESHOLD = 20
TIER3_THRESHOLD = 60

# Flash colors (4-stage sequence)
FLASH_COLORS: list[Color] = [
    (1.0, 1.0, 1.0, 1.0),    # white
    (1.0, 1.0, 1.0, 1.0),    # white
    (1.0, 0.75, 0.2, 1.0),   # amber
    (1.0, 0.75, 0.2, 0.5),   # dimming amber
]

# Clip colors — silver/metallic palette
CLIP_COLORS: list[Color] = [
    (0.70, 0.70, 0.78, 1.0),  # cool silver
    (0.75, 0.75, 0.80, 1.0),  # neutral silver
    (0.80, 0.78, 0.75, 1.0),  # warm silver
    (0.72, 0.73, 0.82, 1.0),  # blue-ish silver
]

# Counter styling
COUNTER_FG: Color = (0.80, 0.80, 0.85, 1.0)  # silver text
COUNTER_BG: Color = (0.10, 0.10, 0.12, 0.7)  # dark semi-transparent

# Earth phase colors
EARTH_OUTLINE: Color = (0.90, 0.90, 0.95, 1.0)    # white outline
EARTH_OCEAN: Color = (0.15, 0.35, 0.85, 1.0)       # blue (full stops only)
EARTH_LAND_HEAVY: Color = (0.15, 0.50, 0.20, 1.0)  # dark green (dense chars)
EARTH_LAND_LIGHT: Color = (0.30, 0.70, 0.35, 1.0)  # light green (thin chars)


# ---------------------------------------------------------------------------
# Paperclip shape templates
# ---------------------------------------------------------------------------
# Each template: list[tuple[dx, dy, character]] relative to anchor

# Tier 0 — single-char (always available)
TIER0_TEMPLATES: list[list[tuple[int, int, str]]] = [
    [(0, 0, "\u2202")],   # ∂
    [(0, 0, "\u00a7")],   # §
]

# Tier 1 — 2-cell horizontal (unlocked at 5+ clips)
TIER1_TEMPLATES: list[list[tuple[int, int, str]]] = [
    [(0, 0, "\u27c3"), (1, 0, "\u2283")],  # ⟃⊃
    [(0, 0, "\u2282"), (1, 0, "\u27c4")],  # ⊂⟄
]

# Tier 2 — 2x3 vertical (unlocked at 20+ clips)
TIER2_TEMPLATES: list[list[tuple[int, int, str]]] = [
    # ╭╮
    # ├│
    # ╰╯
    [(0, 0, "\u256d"), (1, 0, "\u256e"),
     (0, 1, "\u251c"), (1, 1, "\u2502"),
     (0, 2, "\u2570"), (1, 2, "\u256f")],
    # ╭╮
    # │┤
    # ╰╯
    [(0, 0, "\u256d"), (1, 0, "\u256e"),
     (0, 1, "\u2502"), (1, 1, "\u2524"),
     (0, 2, "\u2570"), (1, 2, "\u256f")],
]

# Tier 3 — 3x3 box-drawing (unlocked at 60+ clips)
TIER3_TEMPLATES_3X3: list[list[tuple[int, int, str]]] = [
    # ╭─╮
    # ┤ │
    # ╰─╯
    [(0, 0, "\u256d"), (1, 0, "\u2500"), (2, 0, "\u256e"),
     (0, 1, "\u2524"), (1, 1, " "),     (2, 1, "\u2502"),
     (0, 2, "\u2570"), (1, 2, "\u2500"), (2, 2, "\u256f")],
    # ╭─╮
    # ├─┤
    # ╰─╯
    [(0, 0, "\u256d"), (1, 0, "\u2500"), (2, 0, "\u256e"),
     (0, 1, "\u251c"), (1, 1, "\u2500"), (2, 1, "\u2524"),
     (0, 2, "\u2570"), (1, 2, "\u2500"), (2, 2, "\u256f")],
]

# Tier 3 — 4x2 horizontal (unlocked at 60+ clips)
TIER3_TEMPLATES_4X2: list[list[tuple[int, int, str]]] = [
    # ╭─┬╮
    # ╰──╯
    [(0, 0, "\u256d"), (1, 0, "\u2500"), (2, 0, "\u252c"), (3, 0, "\u256e"),
     (0, 1, "\u2570"), (1, 1, "\u2500"), (2, 1, "\u2500"), (3, 1, "\u256f")],
    # ╭┬─╮
    # ╰──╯
    [(0, 0, "\u256d"), (1, 0, "\u252c"), (2, 0, "\u2500"), (3, 0, "\u256e"),
     (0, 1, "\u2570"), (1, 1, "\u2500"), (2, 1, "\u2500"), (3, 1, "\u256f")],
    # ╭─╮╮
    # ╰──╯
    [(0, 0, "\u256d"), (1, 0, "\u2500"), (2, 0, "\u256e"), (3, 0, "\u256e"),
     (0, 1, "\u2570"), (1, 1, "\u2500"), (2, 1, "\u2500"), (3, 1, "\u256f")],
    # ╭╭─╮
    # ╰──╯
    [(0, 0, "\u256d"), (1, 0, "\u256d"), (2, 0, "\u2500"), (3, 0, "\u256e"),
     (0, 1, "\u2570"), (1, 1, "\u2500"), (2, 1, "\u2500"), (3, 1, "\u256f")],
]

# All tier 3 templates combined
TIER3_TEMPLATES = TIER3_TEMPLATES_3X3 + TIER3_TEMPLATES_4X2

# Tiers ordered largest-first for template selection
ALL_TIERS = [
    (TIER3_THRESHOLD, TIER3_TEMPLATES),
    (TIER2_THRESHOLD, TIER2_TEMPLATES),
    (TIER1_THRESHOLD, TIER1_TEMPLATES),
    (0, TIER0_TEMPLATES),
]


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase(IntEnum):
    IDLE = 0
    SEEDING = 1
    REPLICATING = 2        # wave converts text to clips
    FILLING = 3            # random fill of remaining empty space
    EARTH_TRANSITION = 4   # clear screen, display earth art
    EARTH_REPLICATING = 5  # wave converts earth art to clips
    FADING = 6
    DONE = 7


# ---------------------------------------------------------------------------
# ASCII Earth art
# ---------------------------------------------------------------------------

_EARTH_ART_RAW = """\
                                         ,,Ct]<!I:"^`'''''''''''''`^":Ii<-/J,,
                                    Q1~!;+'..................................:;!<{Y
                               v1<!,....''"`<"''..................................."!~[v
                           j}~I..,(`)rOC0/X[-cx/t|{|-)t{~l+Cc//.........................:+[f
                        |]~I::"">i"{QC+;|n1t1~+>i`!lIl`;I^><`}+!<>:.........................I])
                     |}<..I[iitXYxx/'..."-_-1:IQmI!">;<"]~!~lz:............>]1Yx);............."[/
                   Y-I>t)n)xxnxJzn[........'|l^;ii>!I>+`_'^`/j...............xj+X<................nOY
                QmQ<xxjnr:}n<+v)f>>Qx......YJ+l_l<^>!;>+iCdJ(........................................(O
              QQ);_i-+{<n|/|+;`..]I|-......!f+:<;>;_:>>1C}jQ..................................}r......v|J
            m0(i-"+i<f~>([f<i<j/-_1zn!...xQ]l!><]+`]i}_>'...........................'.........~j'...I'jt"}Z
          QO/<!^})Ii-!>.........rxf'.....z}Il~!/I........|c++[1,................{(+i(<}-|l......I:..1}wvt_"_Y
         f/{-+:+"l'{>.....'}l`+..........;I]{:>..........'[|)(}...............:X+|:]il+l/)_[>[1)1|1(1fzrv-"l;/O
       Y{+_~"l>l]``/<i....~^}>}:i].........',..............................'(n-_~[<{Iti>i[1fxt_---+~[^`|c;~^'i)c
      |_+)I+l'!:I^<;:If)ii;`<"il-tl..................................."^..-v1]}[~_I^/+<<<~<})<]ll!^+~':`'I:>I;!i|
     )Y`_';^`!"^"!J>>lj{>Y^I+<;"``<>................................(},....{(<[[}rv..>}xf_]l>l:<X;!i>>"_'ll[I:li>)0
    )"[_!!''[^}<;^"l)`Yl!<Ili;!>>|v:............................._<{zr{.....i)"t}{..l--i>;I!"i^(<`_x^>"X!li~iiI<+I(0
   /;x~;^Q`l"";;~{"^>iI:<<~I<~..>{jJ............................"v_i_-_-;...I><<:!;()<<l;>">;l>^!lml<I++-:>:^!":i^I/
  j>!<l`'^!"^;:'_l!:]'l<"+l+r(:.....................................]{/rt}_l"<^!i'-"-II>"!I;>^I~;+<}">l(i;`i;:i"!I`-n
  1X`_I'^;`^>l!I};Im!<IX;^..........................................l~_;:!;>^Ii;_"+~><"!l:<I<~+>I~"~>^~I`<l;<]:;`~"^)x
 r..l<!'l"Il"l;">{:i}O>..............................................`<_<>!_;!lI};"+[!l:~>_<l<--;_i`+!^_!;i"mI:';:!"`tC
 _..`;`!:l)I!I>l'>I[c'..........................................';>!~<<>lm<>:-]]![:]>I~i~~X![]/+:..i"<IxII>~:;;~ll'~:1n
O...:X~:;Qi;J!!<;>+.............................................z}l!;l};,...1(l'}f+IiI+<{_.....'<l..!'^lxi`>l;lI><!!+~v
/...,Yi^">[<!_^:{)...............................................,jt}i``~",....])x"i!})"[I!!!l<l"ll^l!<:X<;`I!";!;:I"J}
-....f}l>-:.....-1.............................................._)~!llli>!;!:+.......:...]_>>}"^l;[I>Y^<lY'!l!!`}:l`'l{n
i.....~+l~,.....;..............................................r(>>~_):>~><!{"]-(l..........`i!:>">l]^!!<!^`i;+^il;iI`:c
l......_:<Ix_/'..'x}.......................................>'>>]!;i-~ii:^l!!>I>t{^_~]`i]([(1]i[}JII>>';iJiI>lI~l'!il^!"J
i.......l){~];....1^/f[,.................................l~>_l_~_>;^:iIi+<{};"!^'!ii!]}<1!`}/)";`;!_++;)`!!lI}"!>:"i{[}Q
_..........,[[__.........................................}~-<l]mi;:+-_-~:xl;!!;>"I"]};[I:..>!!`"l};>(l_1>ml!<Iii<!;+"I)J
f.............)-...^<|>.................................^>:i;'i_><>~;Ii!lil;x'l[<x:I`-_[,..,-;;:^!l'!}[....;<`^;l!+_<ifz
0..............l){|iI>^+I`>l............................|~>I+"l-!_>l":;>~;><:"I:;'`;>;:;:!"..^II!:!!`l!(~..."(_!;<I1l:z
 -................{l:_;`!l;^]_^.........................l)<<>{<l"!^`I;l>!]Ix`]:!"I:Y:l'"l;!l..`~~I)_i"-,.....:>^:<"[+tX
 r...............:l!!m"I:JI>`~+i],........................)}l>'>l`>l^!:^!I^ll~;;I`:<"!<I~l`!;`}(Ii;{,........"l>I..(<r0
  1..............)!:m:l'Y!"^Q<;`>]^.........................:{+>_~;>}_[!(`"^'>l^_;;-^"i;'lI`lI"[~l!!.........I{I...{nc
  r>.............]">!mml!<'III~+-{}[_!`.................................~-_>^<!;l!XJil'l>;~l;~;-->-..........>i...,x0
   /:.............+~'>I"`>~l_^!>"ll+;_`>-;I..............................[lI;^~_!)>+:-l!~;~l:!`l-`................)J
    )".............,l];+:>i[l!>I!'lii<+>>+`i.............................<-Im>~`{:_l;_l(>'"~!i<...................-C
     },..............;QI~;l_':!x;~^<>[<>'+^...............................l_i!+}{"}]]:_^I+l<'...................._C
      1i...............>><']+ll_^!>>-!i-1,...............................l)}l>+i}l<+~:-;<1I...................."]
       z<...............,><!`+:><i[I{"![|^...............................}+-'^1`l[`}"^+;xI....................Ij
         {,..............>:]<}+]<!~"1<I[...............................`~[^l~:}^^['}i~`]t`..-!...............-Y
          Y<............."|_;+l~i+<!....................................:-"^_'X[Il-ci!)^J~[)!..............;X
            Y!............>_!-]_+{(z....................................`I+^;+}}Y_<|l..`{/-..............,z
              z+...........<i}~;(x(.....................................>i-l-I}l)f...."r<..............lz
                j)........."]i_}/1......................................!}I<!]]1.....................{/
                   )_........i-]-.......................................`!:`......................I{r
                     f[>......}[}i.............................................................,_(
                        /]i....,1/`.........................................................,~1
                           r{<I...~_,...................................................,i-f
                               c|+l:...............................................";i}x
                                    Of]i:"`..................................^"I~)C
                                         ''Qv{~i;"^``,,,,,,,,,,,,,,,^":l<-t''"""

EARTH_ART: list[str] = [line.rstrip() for line in _EARTH_ART_RAW.split("\n")]

# Heavy land chars — visually dense, blocky glyphs → dark green
_HEAVY_LAND_CHARS = frozenset("QOXZmw0{}[]")


# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _FlashInfo:
    x: int
    y: int
    ch: str          # original character (PTY or earth)
    born_tick: int


@dataclass(slots=True)
class _ClipCell:
    x: int
    y: int
    ch: str
    color: Color


# ---------------------------------------------------------------------------
# PaperclipsEffect
# ---------------------------------------------------------------------------

class PaperclipsEffect:
    EFFECT_META = {
        "name": "paperclips",
        "description": "Paperclip maximizer consumes your terminal",
    }

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

        # PTY cell content
        self._pty_cells: dict[tuple[int, int], str] = {}

        # Consumption (sorted by distance from wave origin)
        self._unconsumed_positions: list[tuple[int, int]] = []
        self._consumed: set[tuple[int, int]] = set()

        # Wave propagation
        self._wave_origin: tuple[float, float] = (0.0, 0.0)
        self._wave_radius: float = 0.0
        self._wave_speed: float = WAVE_SPEED_BASE
        self._position_distances: list[float] = []
        self._wave_frontier_idx: int = 0
        self._eligible_pool: list[tuple[int, int]] = []

        # Placed clip cells
        self._clip_cells: dict[tuple[int, int], _ClipCell] = {}
        self._total_clips = 0  # count of paperclips placed (not cells)

        # Flash cells
        self._flash_cells: dict[tuple[int, int], _FlashInfo] = {}

        # Growth budget accumulator
        self._growth_budget = 0.0
        self._replicating_start_tick = 0

        # Seeding
        self._seeding_start_tick = 0

        self._display_count = 0  # counter display (includes phantom)

        # Fade
        self._fade_start_tick = 0

        # Earth phase
        self._earth_cells: dict[tuple[int, int], tuple[str, Color]] = {}
        self._earth_transition_start_tick = 0
        self._all_tiers_unlocked = False
        self._star_cells: dict[tuple[int, int], tuple[str, Color]] = {}

        # Counter zone positions (reserved from clip placement)
        self._counter_positions: set[tuple[int, int]] = set()
        self._counter_text = ""

        # Ghost-cell erasure
        self._prev_render_positions: set[tuple[int, int]] = set()

    # -- Protocol callbacks ---------------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        w, h = update.size
        if self._phase == Phase.IDLE:
            self._width, self._height = w, h
            if self._idle_until == -1:
                self._idle_until = self._tick_count + self._pick_delay()
        elif (w, h) != (self._width, self._height):
            self._handle_resize(w, h)
        # Always track PTY cell content
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

        # Prune OOB state
        self._clip_cells = {
            pos: cc for pos, cc in self._clip_cells.items()
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        }
        self._consumed = {
            pos for pos in self._consumed
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        }
        self._flash_cells = {
            pos: fi for pos, fi in self._flash_cells.items()
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        }
        self._unconsumed_positions = [
            pos for pos in self._unconsumed_positions
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        ]
        self._earth_cells = {
            pos: v for pos, v in self._earth_cells.items()
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        }
        self._star_cells = {
            pos: v for pos, v in self._star_cells.items()
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        }
        self._eligible_pool = [
            pos for pos in self._eligible_pool
            if 0 <= pos[0] < new_w and 0 <= pos[1] < new_h
        ]

        # Rebuild wave distances
        if self._unconsumed_positions:
            ox, oy = self._wave_origin
            self._position_distances = [
                math.hypot(p[0] - ox, (p[1] - oy) * CELL_ASPECT_Y)
                for p in self._unconsumed_positions
            ]
            self._wave_frontier_idx = len(self._position_distances)
            for i, d in enumerate(self._position_distances):
                if d > self._wave_radius:
                    self._wave_frontier_idx = i
                    break
        else:
            self._position_distances = []
            self._wave_frontier_idx = 0

        # Rebuild counter positions
        self._rebuild_counter_positions()

        # Reset ghost tracking
        self._prev_render_positions = set()

    # -- Scheduling -----------------------------------------------------------

    def _pick_delay(self) -> int:
        return round(self._rng.uniform(0.75, 1.25) * self._idle_secs * 30)

    # -- Wave propagation -----------------------------------------------------

    def _pick_wave_origin(self) -> tuple[float, float]:
        """Random point on one of four screen edges."""
        edge = self._rng.randint(0, 3)
        if edge == 0:  # top
            return (self._rng.uniform(0, self._width - 1), 0.0)
        if edge == 1:  # bottom
            return (self._rng.uniform(0, self._width - 1), float(self._height - 1))
        if edge == 2:  # left
            return (0.0, self._rng.uniform(0, self._height - 1))
        # right
        return (float(self._width - 1), self._rng.uniform(0, self._height - 1))

    def _init_wave(self, positions: list[tuple[int, int]]) -> None:
        """Sort positions by distance from wave origin and init wave state."""
        ox, oy = self._wave_origin
        decorated = [(math.hypot(p[0] - ox, (p[1] - oy) * CELL_ASPECT_Y), p) for p in positions]
        decorated.sort(key=lambda t: t[0])
        self._unconsumed_positions = [p for _, p in decorated]
        self._position_distances = [d for d, _ in decorated]
        self._wave_frontier_idx = 0
        self._eligible_pool = []
        self._wave_radius = 0.0
        self._wave_speed = WAVE_SPEED_BASE

    def _advance_wave_consuming(self) -> None:
        """Advance wave and immediately consume all reached positions (solid front)."""
        self._wave_radius += self._wave_speed
        self._wave_speed = min(WAVE_SPEED_MAX, self._wave_speed + WAVE_ACCEL)

        while self._wave_frontier_idx < len(self._unconsumed_positions):
            if self._position_distances[self._wave_frontier_idx] <= self._wave_radius:
                pos = self._unconsumed_positions[self._wave_frontier_idx]
                self._wave_frontier_idx += 1
                if pos not in self._consumed and pos not in self._counter_positions:
                    self._place_one_clip(pos)
            else:
                break

        self._rebuild_counter_positions()

    def _consume_from_pool(self) -> None:
        """Consume clips from the eligible pool based on growth budget."""
        rate = self._growth_rate()
        self._growth_budget += rate
        while self._growth_budget >= 1.0 and self._eligible_pool:
            idx = self._rng.randint(0, len(self._eligible_pool) - 1)
            pos = self._eligible_pool[idx]
            # Swap-remove for O(1)
            self._eligible_pool[idx] = self._eligible_pool[-1]
            self._eligible_pool.pop()

            if pos in self._consumed or pos in self._counter_positions:
                continue

            if self._place_one_clip(pos):
                self._growth_budget -= 1.0

        self._rebuild_counter_positions()

    # -- Effect lifecycle -----------------------------------------------------

    def _start_effect(self) -> None:
        if self._width == 0 or self._height == 0:
            return  # retry next tick
        # Snapshot consumption queue from current PTY content
        positions = list(self._pty_cells.keys())
        self._consumed = set()
        self._clip_cells = {}
        self._flash_cells = {}
        self._total_clips = 0
        self._display_count = 0
        self._growth_budget = 0.0
        self._all_tiers_unlocked = False
        self._earth_cells = {}
        self._star_cells = {}
        if positions:
            origin = self._rng.choice(positions)
            self._wave_origin = (float(origin[0]), float(origin[1]))
        else:
            self._wave_origin = (float(self._width // 2), float(self._height // 2))
        self._init_wave(positions)
        self._rebuild_counter_positions()
        self._seeding_start_tick = self._tick_count
        self._phase = Phase.SEEDING

    def _reset_state(self) -> None:
        self._unconsumed_positions = []
        self._consumed = set()
        self._clip_cells = {}
        self._flash_cells = {}
        self._total_clips = 0
        self._display_count = 0
        self._growth_budget = 0.0
        self._counter_positions = set()
        self._counter_text = ""
        self._prev_render_positions = set()
        self._fade_start_tick = 0
        self._wave_origin = (0.0, 0.0)
        self._wave_radius = 0.0
        self._wave_speed = WAVE_SPEED_BASE
        self._position_distances = []
        self._wave_frontier_idx = 0
        self._eligible_pool = []
        self._earth_cells = {}
        self._star_cells = {}
        self._all_tiers_unlocked = False

    # -- Earth art parsing ----------------------------------------------------

    def _parse_earth_art(self) -> dict[tuple[int, int], tuple[str, Color]]:
        """Parse EARTH_ART and center it on screen."""
        art_height = len(EARTH_ART)
        art_width = max(len(line) for line in EARTH_ART) if EARTH_ART else 0
        offset_x = max(0, (self._width - art_width) // 2)
        offset_y = max(0, (self._height - art_height) // 2)

        # Pass 1: collect non-space positions in art coordinates
        art_chars: dict[tuple[int, int], str] = {}
        for row, line in enumerate(EARTH_ART):
            for col, ch in enumerate(line):
                if ch != " ":
                    art_chars[(col, row)] = ch

        # Pass 2: mark outline — adjacent to void
        outline_positions: set[tuple[int, int]] = set()
        for (col, row) in art_chars:
            for dc, dr in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                if (col + dc, row + dr) not in art_chars:
                    outline_positions.add((col, row))
                    break

        # Pass 3: classify and map to screen coordinates
        result: dict[tuple[int, int], tuple[str, Color]] = {}
        for (col, row), ch in art_chars.items():
            x, y = offset_x + col, offset_y + row
            if x >= self._width or y >= self._height:
                continue
            if (col, row) in outline_positions:
                color = EARTH_OUTLINE
            elif ch == ".":
                color = EARTH_OCEAN
            elif ch in _HEAVY_LAND_CHARS:
                color = EARTH_LAND_HEAVY
            else:
                color = EARTH_LAND_LIGHT
            result[(x, y)] = (ch, color)
        return result

    def _generate_stars(self) -> None:
        """Generate background stars for the earth scene."""
        self._star_cells = {}
        count = min(30, (self._width * self._height) // 100)
        # Build forbidden zone: Chebyshev distance 3 from any earth cell
        forbidden: set[tuple[int, int]] = set()
        for (ex, ey) in self._earth_cells:
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    forbidden.add((ex + dx, ey + dy))
        star_chars = ["*", "+"]
        max_attempts = count * 10
        placed = 0
        for _ in range(max_attempts):
            if placed >= count:
                break
            x = self._rng.randint(0, self._width - 1)
            y = self._rng.randint(0, self._height - 1)
            if (x, y) in forbidden or (x, y) in self._star_cells:
                continue
            ch = self._rng.choice(star_chars)
            b = self._rng.uniform(0.4, 0.7)
            color: Color = (b * 0.9, b * 0.9, b, 0.8)
            self._star_cells[(x, y)] = (ch, color)
            placed += 1

    # -- Counter --------------------------------------------------------------

    def _format_count(self, count: int) -> str:
        if count >= 1_000_000_000_000_000_000_000_000_000:
            return f"{count / 1e27:.1f}Oc"
        if count >= 1_000_000_000_000_000_000_000_000:
            return f"{count / 1e24:.1f}Sp"
        if count >= 1_000_000_000_000_000_000_000:
            return f"{count / 1e21:.1f}Sx"
        if count >= 1_000_000_000_000_000_000:
            return f"{count / 1e18:.1f}Qi"
        if count >= 1_000_000_000_000_000:
            return f"{count / 1e15:.1f}Q"
        if count >= 1_000_000_000_000:
            return f"{count / 1_000_000_000_000:.1f}T"
        if count >= 1_000_000_000:
            return f"{count / 1_000_000_000:.1f}B"
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    def _counter_label(self) -> str:
        formatted = self._format_count(self._display_count)
        noun = "paperclip" if self._display_count == 1 else "paperclips"
        return f" {formatted} {noun} "

    def _rebuild_counter_positions(self) -> None:
        self._counter_positions = set()
        if self._height < 1 or self._width < 1:
            return
        label = self._counter_label()
        start_x = max(0, (self._width - len(label)) // 2)
        y = self._height - 1
        for i, ch in enumerate(label):
            x = start_x + i
            if 0 <= x < self._width:
                self._counter_positions.add((x, y))

    # -- Phase helpers --------------------------------------------------------

    def _start_fading(self) -> None:
        self._phase = Phase.FADING
        self._fade_start_tick = self._tick_count

    def _fade_alpha(self) -> float:
        if self._phase != Phase.FADING:
            return 1.0
        return max(0.0, 1.0 - (self._tick_count - self._fade_start_tick) / FADE_DURATION)

    def _tint(self, color: Color, alpha: float) -> Color:
        return (color[0], color[1], color[2], color[3] * alpha)

    # -- Growth algorithm -----------------------------------------------------

    def _growth_rate(self) -> float:
        ticks_since = self._tick_count - self._replicating_start_tick
        return min(GROWTH_RATE_CAP, GROWTH_RATE_BASE * (2.0 ** (ticks_since / GROWTH_DOUBLING_TICKS)))

    def _eligible_tiers(self) -> list[list[list[tuple[int, int, str]]]]:
        """Return template lists for all tiers the current clip count qualifies for."""
        if self._all_tiers_unlocked:
            return [templates for _, templates in ALL_TIERS]
        result = []
        for threshold, templates in ALL_TIERS:
            if self._total_clips >= threshold:
                result.append(templates)
        return result

    def _try_place_template(
        self, anchor: tuple[int, int], template: list[tuple[int, int, str]]
    ) -> bool:
        """Try to place a template at anchor. Return True if placed."""
        ax, ay = anchor
        positions = []
        for dx, dy, ch in template:
            x, y = ax + dx, ay + dy
            if not (0 <= x < self._width and 0 <= y < self._height):
                return False
            if (x, y) in self._counter_positions:
                return False
            positions.append((x, y, ch))

        # Place the clip
        color = self._rng.choice(CLIP_COLORS)
        for x, y, ch in positions:
            # Add flash for positions that have content and aren't already clipped
            if (x, y) not in self._clip_cells:
                source_char = self._pty_cells.get((x, y))
                if source_char is None:
                    earth_entry = self._earth_cells.get((x, y))
                    if earth_entry is not None:
                        source_char = earth_entry[0]
                if source_char is not None:
                    self._flash_cells[(x, y)] = _FlashInfo(
                        x=x, y=y, ch=source_char,
                        born_tick=self._tick_count,
                    )
            self._clip_cells[(x, y)] = _ClipCell(x=x, y=y, ch=ch, color=color)
            self._consumed.add((x, y))

        self._total_clips += 1
        self._display_count = max(self._display_count, self._total_clips)
        return True

    def _place_one_clip(self, pos: tuple[int, int]) -> bool:
        """Try to place a clip at pos using random tier selection."""
        if pos in self._consumed:
            return False
        if not (0 <= pos[0] < self._width and 0 <= pos[1] < self._height):
            return False
        if pos in self._counter_positions:
            return False

        eligible = self._eligible_tiers()
        if not eligible:
            return False

        # Pick a random eligible tier
        chosen_tier = self._rng.choice(eligible)
        shuffled = list(chosen_tier)
        self._rng.shuffle(shuffled)
        for template in shuffled:
            if self._try_place_template(pos, template):
                return True

        # Fall through to remaining tiers
        remaining = [t for t in eligible if t is not chosen_tier]
        self._rng.shuffle(remaining)
        for tier in remaining:
            shuffled = list(tier)
            self._rng.shuffle(shuffled)
            for template in shuffled:
                if self._try_place_template(pos, template):
                    return True

        return False

    # -- Flash management -----------------------------------------------------

    def _prune_flashes(self) -> None:
        self._flash_cells = {
            pos: fi for pos, fi in self._flash_cells.items()
            if self._tick_count - fi.born_tick < FLASH_DURATION
        }

    # -- Rendering ------------------------------------------------------------

    def _render(self) -> list[OutputMessage]:
        cells: list[Cell] = []
        current_positions: set[tuple[int, int]] = set()
        alpha = self._fade_alpha()

        # 0. Stars (earth background)
        if self._phase in (Phase.EARTH_TRANSITION, Phase.EARTH_REPLICATING, Phase.FADING):
            for pos, (ch, color) in self._star_cells.items():
                if pos not in self._clip_cells and pos not in self._flash_cells:
                    fg = self._tint(color, alpha)
                    cells.append(Cell(character=ch, coordinates=pos, fg=fg, bg=None))
                    current_positions.add(pos)

        # 1. Earth art cells (unconsumed, during earth phases)
        if self._phase in (Phase.EARTH_TRANSITION, Phase.EARTH_REPLICATING):
            for pos, (ch, color) in self._earth_cells.items():
                if pos not in self._clip_cells and pos not in self._flash_cells:
                    fg = self._tint(color, alpha)
                    cells.append(Cell(character=ch, coordinates=pos, fg=fg, bg=None))
                    current_positions.add(pos)

        # 2. Clip cells (skip positions with active flashes)
        for pos, cc in self._clip_cells.items():
            if pos in self._flash_cells:
                continue
            fg = self._tint(cc.color, alpha)
            cells.append(Cell(character=cc.ch, coordinates=pos, fg=fg, bg=None))
            current_positions.add(pos)

        # 3. Flash cells
        for pos, fi in self._flash_cells.items():
            stage = self._tick_count - fi.born_tick
            if stage < FLASH_DURATION:
                flash_color = FLASH_COLORS[stage]
                fg = self._tint(flash_color, alpha)
                cells.append(Cell(character=fi.ch, coordinates=pos, fg=fg, bg=None))
                current_positions.add(pos)

        # 4. Counter cells
        if self._phase in (Phase.REPLICATING, Phase.FILLING,
                           Phase.EARTH_TRANSITION, Phase.EARTH_REPLICATING,
                           Phase.FADING):
            label = self._counter_label()
            start_x = max(0, (self._width - len(label)) // 2)
            y = self._height - 1
            if 0 <= y < self._height:
                for i, ch in enumerate(label):
                    x = start_x + i
                    if 0 <= x < self._width:
                        pos = (x, y)
                        fg = self._tint(COUNTER_FG, alpha)
                        bg = self._tint(COUNTER_BG, alpha)
                        cells.append(Cell(character=ch, coordinates=pos, fg=fg, bg=bg))
                        current_positions.add(pos)

        # 5. Ghost erasure
        erasers = [
            Cell(character=" ", coordinates=pos, fg=None, bg=None)
            for pos in self._prev_render_positions - current_positions
        ]
        self._prev_render_positions = current_positions

        return [OutputCells(cells=erasers + cells)]

    # -- Main tick ------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def cancel(self) -> None:
        """Begin fading from any active phase."""
        if self._phase in (
            Phase.SEEDING, Phase.REPLICATING, Phase.FILLING,
            Phase.EARTH_TRANSITION, Phase.EARTH_REPLICATING,
        ):
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

        if self._phase == Phase.SEEDING:
            if self._tick_count - self._seeding_start_tick >= SEEDING_DURATION:
                # Place one seed clip at closest position to wave origin
                for pos in self._unconsumed_positions:
                    if pos not in self._consumed:
                        template = self._rng.choice(TIER0_TEMPLATES)
                        self._try_place_template(pos, template)
                        break
                self._replicating_start_tick = self._tick_count
                self._phase = Phase.REPLICATING
                self._rebuild_counter_positions()
            return self._render()

        if self._phase == Phase.REPLICATING:
            self._prune_flashes()
            self._advance_wave_consuming()
            # Transition: wave done and no flashes
            wave_done = self._wave_frontier_idx >= len(self._unconsumed_positions)
            if wave_done and not self._flash_cells:
                # Enter FILLING — collect all empty positions
                empty_positions = [
                    (x, y)
                    for y in range(self._height)
                    for x in range(self._width)
                    if (x, y) not in self._consumed
                    and (x, y) not in self._counter_positions
                ]
                self._rng.shuffle(empty_positions)
                self._eligible_pool = empty_positions
                self._phase = Phase.FILLING
            return self._render()

        if self._phase == Phase.FILLING:
            self._prune_flashes()
            self._consume_from_pool()
            if not self._eligible_pool and not self._flash_cells:
                # Clear for earth phase
                self._clip_cells = {}
                self._flash_cells = {}
                self._consumed = set()
                self._earth_cells = self._parse_earth_art()
                self._generate_stars()
                self._earth_transition_start_tick = self._tick_count
                self._rebuild_counter_positions()
                self._phase = Phase.EARTH_TRANSITION
            return self._render()

        if self._phase == Phase.EARTH_TRANSITION:
            if self._tick_count - self._earth_transition_start_tick >= EARTH_TRANSITION_DURATION:
                # Start earth replicating
                self._all_tiers_unlocked = True
                earth_positions = list(self._earth_cells.keys())
                if earth_positions:
                    origin = self._rng.choice(earth_positions)
                    self._wave_origin = (float(origin[0]), float(origin[1]))
                else:
                    self._wave_origin = self._pick_wave_origin()
                self._init_wave(earth_positions)
                self._consumed = set()
                self._replicating_start_tick = self._tick_count
                self._growth_budget = 0.0
                self._phase = Phase.EARTH_REPLICATING
            return self._render()

        if self._phase == Phase.EARTH_REPLICATING:
            self._prune_flashes()
            self._advance_wave_consuming()
            # Phantom counter acceleration
            ticks_in = self._tick_count - self._replicating_start_tick
            phantom_rate = 10.0 ** (ticks_in * 0.1)
            self._display_count += int(phantom_rate)
            self._rebuild_counter_positions()
            wave_done = self._wave_frontier_idx >= len(self._unconsumed_positions)
            if wave_done and not self._flash_cells:
                self._display_count = max(self._display_count, TARGET_PAPERCLIPS)
                self._start_fading()
            return self._render()

        if self._phase == Phase.FADING:
            self._prune_flashes()
            if self._fade_alpha() <= 0.0:
                result = self._render()
                self._phase = Phase.DONE
                return result
            return self._render()

        return []


EFFECT_META = PaperclipsEffect.EFFECT_META

if __name__ == "__main__":
    run(PaperclipsEffect())
