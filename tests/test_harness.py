"""Tests for clippy.harness — step() and run()."""
import io
import json
import os
import queue
import threading

import pytest

from clippy.harness import step, run
from clippy.types import (
    OutputText,
    OutputCells,
    OutputPixels,
    PTYUpdate,
    TTYResize,
    Cell,
    Pixel,
)


class RecordingEffect:
    """Minimal Effect that records callbacks and returns configurable output."""

    def __init__(self, tick_output=None):
        self.updates = []
        self.resizes = []
        self._tick_output = tick_output or []

    def on_pty_update(self, update):
        self.updates.append(update)

    def on_resize(self, resize):
        self.resizes.append(resize)

    def tick(self):
        return list(self._tick_output)


class MessageReader:
    """Test reader that yields lines then blocks until stopped.

    Prevents the stdin listener from setting shutdown prematurely
    (which happens with io.StringIO that reaches EOF instantly).
    """

    def __init__(self, text=""):
        self._lines = text.splitlines(keepends=True)
        self._stop = threading.Event()

    def __iter__(self):
        yield from self._lines
        # Block so listener thread doesn't set shutdown
        while not self._stop.is_set():
            self._stop.wait(timeout=0.05)

    def stop(self):
        self._stop.set()


# --- step() tests ---


def test_step_pty_update_dispatches():
    effect = RecordingEffect()
    raw = '{"pty_update": {"size": [80, 24], "cells": []}}'
    step(effect, [raw])
    assert len(effect.updates) == 1
    assert isinstance(effect.updates[0], PTYUpdate)
    assert effect.updates[0].size == (80, 24)


def test_step_tty_resize_dispatches():
    effect = RecordingEffect()
    raw = '{"tty_resize": {"width": 120, "height": 40}}'
    step(effect, [raw])
    assert len(effect.resizes) == 1
    assert isinstance(effect.resizes[0], TTYResize)
    assert effect.resizes[0].width == 120


def test_step_malformed_skipped():
    effect = RecordingEffect()
    messages = [
        '{"pty_update": {"size": [80, 24], "cells": []}}',
        "not json",
        '{"tty_resize": {"width": 120, "height": 40}}',
    ]
    step(effect, messages)
    assert len(effect.updates) == 1
    assert len(effect.resizes) == 1


def test_step_empty_messages():
    output = [OutputText(text="hi", coordinates=(0, 0),
                         fg=(1.0, 1.0, 1.0, 1.0), bg=None)]
    effect = RecordingEffect(tick_output=output)
    result = step(effect, [])
    assert len(result) == 1
    data = json.loads(result[0])
    assert "output_text" in data


def test_step_tick_output_serialized():
    cell = Cell(character="X", coordinates=(0, 0),
                fg=(1.0, 0.0, 0.0, 1.0), bg=None)
    output = [OutputCells(cells=[cell])]
    effect = RecordingEffect(tick_output=output)
    result = step(effect, [])
    assert len(result) == 1
    data = json.loads(result[0])
    assert "output_cells" in data
    assert isinstance(data["output_cells"], list)


def test_step_empty_tick():
    effect = RecordingEffect(tick_output=[])
    result = step(effect, [])
    assert result == []


# --- run() tests ---


def test_run_dispatches_messages():
    """Feed messages via reader, verify callbacks fired."""
    reader = MessageReader(
        '{"pty_update": {"size": [80, 24], "cells": []}}\n'
        '{"tty_resize": {"width": 120, "height": 40}}\n'
    )

    class WaitForMessages:
        def __init__(self):
            self.updates = []
            self.resizes = []

        def on_pty_update(self, update):
            self.updates.append(update)

        def on_resize(self, resize):
            self.resizes.append(resize)

        def tick(self):
            if self.updates and self.resizes:
                reader.stop()
                raise KeyboardInterrupt
            return []

    effect = WaitForMessages()
    run(
        effect,
        fps=1000,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )

    assert len(effect.updates) == 1
    assert isinstance(effect.updates[0], PTYUpdate)
    assert len(effect.resizes) == 1
    assert isinstance(effect.resizes[0], TTYResize)


def test_run_flush_on_output():
    """Verify flush called after non-empty output."""
    flush_count = [0]
    lines = []
    reader = MessageReader()  # No messages, blocks

    class OutputThenExit:
        def __init__(self):
            self.ticked = False

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            if not self.ticked:
                self.ticked = True
                return [OutputText(text="hi", coordinates=(0, 0),
                                   fg=(1.0, 1.0, 1.0, 1.0), bg=None)]
            reader.stop()
            raise KeyboardInterrupt

    def fake_flush():
        flush_count[0] += 1

    run(
        OutputThenExit(),
        fps=1000,
        writer=lambda s: lines.append(s),
        flush=fake_flush,
        reader=reader,
    )

    assert flush_count[0] >= 1
    assert any("output_text" in line for line in lines)


def test_run_no_write_on_empty_tick():
    """Verify nothing written when tick returns empty."""
    lines = []
    reader = MessageReader()  # No messages, blocks
    tick_count = [0]

    class EmptyThenExit:
        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            tick_count[0] += 1
            if tick_count[0] >= 3:
                reader.stop()
                raise KeyboardInterrupt
            return []

    run(
        EmptyThenExit(),
        fps=1000,
        writer=lambda s: lines.append(s),
        flush=lambda: None,
        reader=reader,
    )

    assert lines == []


def test_run_stdin_eof_clean_exit():
    """stdin EOF causes clean exit (run returns, doesn't hang)."""
    reader = io.StringIO("")  # Immediate EOF

    class NoopEffect:
        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            return []

    # Should return cleanly — if it hangs, the test framework will timeout
    run(
        NoopEffect(),
        fps=1000,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )


def test_run_effect_exception_caught():
    """Effect exception in tick is caught, harness doesn't crash."""
    reader = MessageReader()  # Blocks until stopped

    class CrashingEffect:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            if self.tick_count == 1:
                raise ValueError("boom")
            reader.stop()
            raise KeyboardInterrupt

    effect = CrashingEffect()
    # Should not raise ValueError — it's caught internally
    run(
        effect,
        fps=1000,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )

    assert effect.tick_count >= 2


def test_run_callback_exception_caught():
    """Exception in on_pty_update is caught, harness continues."""
    reader = MessageReader(
        '{"pty_update": {"size": [80, 24], "cells": []}}\n'
    )

    class CrashingCallback:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            raise RuntimeError("callback crash")

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            if self.tick_count >= 3:
                reader.stop()
                raise KeyboardInterrupt
            return []

    effect = CrashingCallback()
    run(
        effect,
        fps=1000,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )

    assert effect.tick_count >= 2


def test_run_with_fake_clock():
    """FPS/timing with fake clock."""
    reader = MessageReader()
    fake_time = [0.0]
    ticks = []

    class TimedEffect:
        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            ticks.append(fake_time[0])
            if len(ticks) >= 3:
                reader.stop()
                raise KeyboardInterrupt
            # Simulate time passing within tick
            fake_time[0] += 0.01
            return []

    run(
        TimedEffect(),
        fps=30,
        clock=lambda: fake_time[0],
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )

    assert len(ticks) >= 3


def test_run_invalid_fps_env(monkeypatch):
    """CLIPPY_FPS=banana doesn't crash — falls back to default."""
    monkeypatch.setenv("CLIPPY_FPS", "banana")
    reader = MessageReader()

    class ExitOnTick:
        def on_pty_update(self, update):
            pass
        def on_resize(self, resize):
            pass
        def tick(self):
            reader.stop()
            raise KeyboardInterrupt

    run(
        ExitOnTick(),
        fps=30,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )


def test_run_zero_fps_env_clamped(monkeypatch):
    """CLIPPY_FPS=0 is clamped to 1, doesn't crash."""
    monkeypatch.setenv("CLIPPY_FPS", "0")
    reader = MessageReader()

    class ExitOnTick:
        def on_pty_update(self, update):
            pass
        def on_resize(self, resize):
            pass
        def tick(self):
            reader.stop()
            raise KeyboardInterrupt

    run(
        ExitOnTick(),
        fps=30,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )


def test_run_broken_pipe_exits_cleanly():
    """BrokenPipeError in writer triggers clean shutdown."""
    reader = MessageReader()

    class OutputEffect:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            return [OutputText(text="hi", coordinates=(0, 0),
                               fg=(1.0, 1.0, 1.0, 1.0), bg=None)]

    def broken_writer(s):
        raise BrokenPipeError("pipe closed")

    effect = OutputEffect()
    run(
        effect,
        fps=1000,
        writer=broken_writer,
        flush=lambda: None,
        reader=reader,
    )
    reader.stop()
    # Should have exited cleanly after the first BrokenPipeError
    assert effect.tick_count >= 1


def test_run_clear_frame_sent_when_effect_goes_quiet():
    """After returning cells, a one-shot empty OutputCells is sent when tick() returns []."""
    lines = []
    reader = MessageReader()
    cell = Cell(character="X", coordinates=(0, 0), fg=(1.0, 0.0, 0.0, 1.0), bg=None)

    class ActiveThenQuiet:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            if self.tick_count == 1:
                return [OutputCells(cells=[cell])]
            if self.tick_count == 3:
                reader.stop()
                raise KeyboardInterrupt
            return []

    run(
        ActiveThenQuiet(),
        fps=1000,
        writer=lambda s: lines.append(s),
        flush=lambda: None,
        reader=reader,
    )

    assert len(lines) == 2
    data0 = json.loads(lines[0])
    assert "output_cells" in data0
    assert len(data0["output_cells"]) == 1  # the real frame

    data1 = json.loads(lines[1])
    assert "output_cells" in data1
    assert data1["output_cells"] == []  # the clear frame


def test_run_clear_frame_sent_only_once():
    """The clear frame is sent exactly once, not every idle tick."""
    lines = []
    reader = MessageReader()
    cell = Cell(character="X", coordinates=(0, 0), fg=(1.0, 0.0, 0.0, 1.0), bg=None)

    class ActiveThenManyQuiet:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            if self.tick_count == 1:
                return [OutputCells(cells=[cell])]
            if self.tick_count >= 5:
                reader.stop()
                raise KeyboardInterrupt
            return []

    run(
        ActiveThenManyQuiet(),
        fps=1000,
        writer=lambda s: lines.append(s),
        flush=lambda: None,
        reader=reader,
    )

    # One real frame + one clear frame; subsequent idle ticks write nothing
    assert len(lines) == 2
    assert json.loads(lines[1])["output_cells"] == []


def test_run_clear_frame_sent_for_output_pixels():
    """After returning pixels, a one-shot empty OutputPixels is sent when tick() returns []."""
    lines = []
    reader = MessageReader()
    pixel = Pixel(coordinates=(10, 5), color=(0.0, 1.0, 0.0, 1.0))

    class PixelsThenQuiet:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            if self.tick_count == 1:
                return [OutputPixels(pixels=[pixel])]
            if self.tick_count == 3:
                reader.stop()
                raise KeyboardInterrupt
            return []

    run(
        PixelsThenQuiet(),
        fps=1000,
        writer=lambda s: lines.append(s),
        flush=lambda: None,
        reader=reader,
    )

    assert len(lines) == 2
    data0 = json.loads(lines[0])
    assert "output_pixels" in data0
    assert len(data0["output_pixels"]) == 1  # the real frame

    data1 = json.loads(lines[1])
    assert "output_pixels" in data1
    assert data1["output_pixels"] == []  # the clear frame


def test_run_to_json_exception_continues():
    """Bad to_json() is caught, loop continues."""
    reader = MessageReader()

    class BadOutput:
        def to_json(self):
            raise TypeError("cannot serialize")

    class BadThenGoodEffect:
        def __init__(self):
            self.tick_count = 0

        def on_pty_update(self, update):
            pass

        def on_resize(self, resize):
            pass

        def tick(self):
            self.tick_count += 1
            if self.tick_count == 1:
                return [BadOutput()]
            reader.stop()
            raise KeyboardInterrupt

    effect = BadThenGoodEffect()
    run(
        effect,
        fps=1000,
        writer=lambda s: None,
        flush=lambda: None,
        reader=reader,
    )
    assert effect.tick_count >= 2
