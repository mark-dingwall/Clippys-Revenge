"""Protocol message types for the tattoy plugin protocol.

Defines dataclasses for all input/output message types and
JSON serialization/deserialization matching tattoy's wire format.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

Color = tuple[float, float, float, float]  # RGBA, 0.0-1.0


@dataclass(slots=True)
class Cell:
    character: str
    coordinates: tuple[int, int]
    fg: Color | None
    bg: Color | None


@dataclass(slots=True)
class Pixel:
    coordinates: tuple[int, int]
    color: Color | None = None


@dataclass(slots=True)
class PTYUpdate:
    size: tuple[int, int]
    cells: list[Cell]
    cursor: tuple[int, int] = (0, 0)


@dataclass(slots=True)
class TTYResize:
    width: int
    height: int


@dataclass(slots=True)
class OutputText:
    text: str
    coordinates: tuple[int, int]
    fg: Color | None
    bg: Color | None

    def to_json(self) -> str:
        return json.dumps({"output_text": {
            "text": self.text,
            "coordinates": list(self.coordinates),
            "fg": list(self.fg) if self.fg is not None else None,
            "bg": list(self.bg) if self.bg is not None else None,
        }})


@dataclass(slots=True)
class OutputCells:
    cells: list[Cell]

    def to_json(self) -> str:
        return json.dumps({"output_cells": [
            {
                "character": c.character,
                "coordinates": list(c.coordinates),
                "fg": list(c.fg) if c.fg is not None else None,
                "bg": list(c.bg) if c.bg is not None else None,
            }
            for c in self.cells
        ]})


@dataclass(slots=True)
class OutputPixels:
    pixels: list[Pixel]

    def to_json(self) -> str:
        return json.dumps({"output_pixels": [
            {
                "coordinates": list(p.coordinates),
                "color": list(p.color) if p.color is not None else None,
            }
            for p in self.pixels
        ]})


InputMessage = PTYUpdate | TTYResize
OutputMessage = OutputText | OutputCells | OutputPixels


class CursorShakeDetector:
    """Detects rapid left-right cursor shake: 5 x-axis reversals within 2 seconds."""

    WINDOW_TICKS = 60   # 2s at 30fps
    REVERSALS_NEEDED = 5

    def __init__(self) -> None:
        self._last_x: int | None = None
        self._last_x_dir: int = 0          # +1 or -1, last non-zero dx direction
        self._reversal_ticks: list[int] = []  # tick numbers of each reversal
        self._tick: int = 0

    def update(self, pos: tuple[int, int]) -> bool:
        """Record cursor position, return True if shake gesture completed."""
        self._tick += 1
        x = pos[0]

        if self._last_x is not None:
            dx = x - self._last_x
            if dx != 0:
                direction = 1 if dx > 0 else -1
                if self._last_x_dir != 0 and direction != self._last_x_dir:
                    self._reversal_ticks.append(self._tick)
                self._last_x_dir = direction

        self._last_x = x

        # Prune reversals outside the window
        cutoff = self._tick - self.WINDOW_TICKS
        self._reversal_ticks = [t for t in self._reversal_ticks if t > cutoff]

        if len(self._reversal_ticks) >= self.REVERSALS_NEEDED:
            self._reversal_ticks.clear()
            self._last_x = None
            self._last_x_dir = 0
            return True
        return False

    def reset(self) -> None:
        """Clear all accumulated state. Call at phase boundaries."""
        self._last_x = None
        self._last_x_dir = 0
        self._reversal_ticks.clear()


def _validated_tuple(seq, length: int) -> tuple:
    """Convert to tuple and verify expected length."""
    t = tuple(seq)
    if len(t) != length:
        raise ValueError(f"Expected {length} elements, got {len(t)}")
    return t


def from_json(raw: str) -> InputMessage | None:
    """Parse a JSON line into an InputMessage. Returns None for any malformed input."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None

        if "pty_update" in data:
            payload = data["pty_update"]
            if not isinstance(payload, dict):
                return None
            size = _validated_tuple(payload["size"], 2)
            cells = [
                Cell(
                    character=c["character"],
                    coordinates=_validated_tuple(c["coordinates"], 2),
                    fg=_validated_tuple(c["fg"], 4) if c["fg"] is not None else None,
                    bg=_validated_tuple(c["bg"], 4) if c["bg"] is not None else None,
                )
                for c in payload.get("cells", [])
            ]
            cursor = _validated_tuple(payload.get("cursor", [0, 0]), 2)
            return PTYUpdate(size=size, cells=cells, cursor=cursor)

        if "tty_resize" in data:
            payload = data["tty_resize"]
            if not isinstance(payload, dict):
                return None
            return TTYResize(width=payload["width"], height=payload["height"])

        return None
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError):
        return None
