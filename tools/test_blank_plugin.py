#!/usr/bin/env python3
"""Minimal tattoy plugin for diagnosing cell rendering.

Tests 3 things visually:

  TEST 1 (rows 0-2): REPLACE vs RETAIN semantics
    Frame 1: fills rows 0-2 with red "A" chars
    Frame 2+: sends only ONE cell at (0,0) as green "B"
    → If row 0-2 stays red (except (0,0)): RETAIN semantics
    → If only (0,0) shows green B, rest blank: REPLACE semantics

  TEST 2 (rows 4-6): bg=None transparency
    Sends space chars with bg=None every frame
    → If terminal text hidden: bg=None is opaque on this layer
    → If terminal text visible: bg=None is transparent

  TEST 3 (rows 8-10): Opaque bg coverage
    Sends space chars with bg=[0,0,0,1] every frame
    → If terminal text hidden: opaque bg works
    → If terminal text visible: something else is wrong

Usage:
    python3 -m clippy.launcher --effect unified_runner  # normal mode
    # OR test directly by configuring tattoy.toml to point at this file
"""
import json
import sys
import time


def main():
    width, height = 80, 24

    # Wait for first PTY update to get terminal size
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            msg = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if "pty_update" in msg:
            size = msg["pty_update"].get("size", [80, 24])
            width, height = size[0], size[1]
            break

    # ---- FRAME 1: Fill test zones ----
    cells = []

    # TEST 1: rows 0-2 — fill with red A's
    for y in range(min(3, height)):
        for x in range(width):
            cells.append({
                "character": "A",
                "coordinates": [x, y],
                "fg": [1.0, 0.0, 0.0, 1.0],
                "bg": [0.2, 0.0, 0.0, 1.0],
            })

    # TEST 2: rows 4-6 — space with bg=null
    for y in range(4, min(7, height)):
        for x in range(width):
            cells.append({
                "character": " ",
                "coordinates": [x, y],
                "fg": None,
                "bg": None,
            })

    # TEST 3: rows 8-10 — space with opaque black bg
    for y in range(8, min(11, height)):
        for x in range(width):
            cells.append({
                "character": " ",
                "coordinates": [x, y],
                "fg": None,
                "bg": [0.0, 0.0, 0.0, 1.0],
            })

    frame1 = json.dumps({"output_cells": cells})
    sys.stdout.write(frame1 + "\n")
    sys.stdout.flush()
    time.sleep(0.5)  # Show frame 1 briefly

    # ---- FRAME 2+: Only send one cell (green B at 0,0) ----
    # Plus re-send test 2 and test 3 zones
    while True:
        cells2 = []

        # TEST 1 continuation: just one cell
        cells2.append({
            "character": "B",
            "coordinates": [0, 0],
            "fg": [0.0, 1.0, 0.0, 1.0],
            "bg": [0.0, 0.2, 0.0, 1.0],
        })

        # TEST 2: re-send bg=null zone every frame
        for y in range(4, min(7, height)):
            for x in range(width):
                cells2.append({
                    "character": " ",
                    "coordinates": [x, y],
                    "fg": None,
                    "bg": None,
                })

        # TEST 3: re-send opaque bg zone every frame
        for y in range(8, min(11, height)):
            for x in range(width):
                cells2.append({
                    "character": " ",
                    "coordinates": [x, y],
                    "fg": None,
                    "bg": [0.0, 0.0, 0.0, 1.0],
                })

        frame2 = json.dumps({"output_cells": cells2})
        try:
            sys.stdout.write(frame2 + "\n")
            sys.stdout.flush()
            # Also drain stdin to prevent buffer bloat
            time.sleep(1.0 / 30)
        except (BrokenPipeError, IOError):
            break


if __name__ == "__main__":
    main()
