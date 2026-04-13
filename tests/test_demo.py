"""Tests for clippy.demo — ANSI helpers, render_frame, and demo_run."""
from __future__ import annotations

import pytest

from clippy.demo import (
    ALT_SCREEN_OFF,
    ALT_SCREEN_ON,
    CLEAR,
    HIDE_CURSOR,
    RESET,
    SHOW_CURSOR,
    color_to_bg,
    color_to_fg,
    demo_run,
    move_to,
    render_frame,
)
from clippy.types import (
    Cell,
    Color,
    OutputCells,
    OutputPixels,
    OutputText,
    Pixel,
)


# ---------------------------------------------------------------------------
# ANSI helper tests
# ---------------------------------------------------------------------------

class TestColorToFg:
    def test_red(self):
        assert color_to_fg((1.0, 0.0, 0.0, 1.0)) == "\033[38;2;255;0;0m"

    def test_green(self):
        assert color_to_fg((0.0, 1.0, 0.0, 1.0)) == "\033[38;2;0;255;0m"

    def test_none_returns_empty(self):
        assert color_to_fg(None) == ""

    def test_clamp_high(self):
        result = color_to_fg((2.0, 0.0, 0.0, 1.0))
        assert result == "\033[38;2;255;0;0m"

    def test_clamp_low(self):
        result = color_to_fg((-1.0, 0.0, 0.0, 1.0))
        assert result == "\033[38;2;0;0;0m"


class TestColorToBg:
    def test_blue(self):
        assert color_to_bg((0.0, 0.0, 1.0, 1.0)) == "\033[48;2;0;0;255m"

    def test_none_returns_empty(self):
        assert color_to_bg(None) == ""


class TestMoveTo:
    def test_origin(self):
        assert move_to(0, 0) == "\033[1;1H"

    def test_offset(self):
        assert move_to(5, 3) == "\033[4;6H"


# ---------------------------------------------------------------------------
# render_frame tests
# ---------------------------------------------------------------------------

class TestRenderFrame:
    def _capture(self, outputs):
        """Render outputs and return captured string."""
        buf = []
        render_frame(outputs, buf.append, lambda: None)
        return "".join(buf)

    def test_output_cells(self):
        cell = Cell(character="X", coordinates=(5, 3),
                    fg=(1.0, 0.0, 0.0, 1.0), bg=None)
        result = self._capture([OutputCells(cells=[cell])])
        assert move_to(5, 3) in result
        assert "\033[38;2;255;0;0m" in result
        assert "X" in result
        assert RESET in result

    def test_output_cells_with_bg(self):
        cell = Cell(character="@", coordinates=(0, 0),
                    fg=(1.0, 1.0, 1.0, 1.0), bg=(0.0, 0.0, 0.0, 1.0))
        result = self._capture([OutputCells(cells=[cell])])
        assert "\033[48;2;0;0;0m" in result

    def test_output_text(self):
        text = OutputText(text="hello", coordinates=(10, 5),
                          fg=(0.0, 1.0, 0.0, 1.0), bg=None)
        result = self._capture([text])
        assert move_to(10, 5) in result
        assert "hello" in result
        assert RESET in result

    def test_output_pixels(self):
        # pixel y=4 (even) → cell_y=2, upper half block ▀
        pixel = Pixel(coordinates=(2, 4), color=(1.0, 0.5, 0.0, 1.0))
        result = self._capture([OutputPixels(pixels=[pixel])])
        assert move_to(2, 2) in result
        assert "\u2580" in result  # ▀ upper half
        assert RESET in result

    def test_output_pixels_lower_half(self):
        # pixel y=5 (odd) → cell_y=2, lower half block ▄
        pixel = Pixel(coordinates=(3, 5), color=(0.0, 1.0, 0.5, 1.0))
        result = self._capture([OutputPixels(pixels=[pixel])])
        assert move_to(3, 2) in result
        assert "\u2584" in result  # ▄ lower half
        assert RESET in result

    def test_output_pixels_null_color_skipped(self):
        # ghost erasure pixels (color=None) must not render any block character
        pixel = Pixel(coordinates=(5, 6), color=None)
        result = self._capture([OutputPixels(pixels=[pixel])])
        assert "\u2580" not in result
        assert "\u2584" not in result

    def test_empty_outputs(self):
        flush_count = [0]
        buf = []
        render_frame([], buf.append, lambda: flush_count.__setitem__(0, flush_count[0] + 1))
        assert buf == []
        assert flush_count[0] == 1  # flush always called

    def test_mixed_outputs_render_in_order(self):
        cell = Cell(character="A", coordinates=(0, 0),
                    fg=(1.0, 0.0, 0.0, 1.0), bg=None)
        text = OutputText(text="B", coordinates=(1, 0),
                          fg=(0.0, 1.0, 0.0, 1.0), bg=None)
        result = self._capture([OutputCells(cells=[cell]), text])
        a_pos = result.index("A")
        b_pos = result.index("B")
        assert a_pos < b_pos

    def test_flush_called(self):
        flush_count = [0]
        cell = Cell(character="X", coordinates=(0, 0),
                    fg=(1.0, 0.0, 0.0, 1.0), bg=None)
        render_frame(
            [OutputCells(cells=[cell])],
            lambda s: None,
            lambda: flush_count.__setitem__(0, flush_count[0] + 1),
        )
        assert flush_count[0] == 1


# ---------------------------------------------------------------------------
# demo_run tests
# ---------------------------------------------------------------------------

class _SimpleEffect:
    """Effect that counts ticks and optionally stops after N ticks."""

    def __init__(self, max_ticks=3):
        self.tick_count = 0
        self.max_ticks = max_ticks
        self.updates = []
        self._done = False

    def on_pty_update(self, update):
        self.updates.append(update)

    def on_resize(self, resize):
        pass

    @property
    def is_done(self):
        return self._done

    def tick(self):
        self.tick_count += 1
        if self.tick_count >= self.max_ticks:
            self._done = True
        return []


class TestDemoRun:
    def test_first_frame_sends_setup(self):
        buf = []
        effect = _SimpleEffect(max_ticks=1)

        demo_run(
            effect, 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=buf.append,
            flush=lambda: None,
        )

        joined = "".join(buf)
        assert ALT_SCREEN_ON in joined
        assert HIDE_CURSOR in joined
        assert CLEAR in joined

    def test_cleanup_on_exit(self):
        buf = []
        effect = _SimpleEffect(max_ticks=1)

        demo_run(
            effect, 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=buf.append,
            flush=lambda: None,
        )

        joined = "".join(buf)
        assert SHOW_CURSOR in joined
        assert ALT_SCREEN_OFF in joined

    def test_effect_receives_pty_update(self):
        effect = _SimpleEffect(max_ticks=1)

        demo_run(
            effect, 120, 40,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=lambda s: None,
            flush=lambda: None,
        )

        assert len(effect.updates) == 1
        assert effect.updates[0].size == (120, 40)

    def test_tick_called_each_frame(self):
        effect = _SimpleEffect(max_ticks=5)

        demo_run(
            effect, 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=lambda s: None,
            flush=lambda: None,
        )

        assert effect.tick_count == 5

    def test_cleanup_on_effect_exception(self):
        buf = []

        class CrashEffect:
            def on_pty_update(self, update):
                pass
            def on_resize(self, resize):
                pass
            def tick(self):
                raise RuntimeError("boom")

        # Exception is now caught by demo_run, not propagated
        demo_run(
            CrashEffect(), 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=buf.append,
            flush=lambda: None,
        )

        joined = "".join(buf)
        assert SHOW_CURSOR in joined
        assert ALT_SCREEN_OFF in joined

    def test_stops_on_phase_done(self):
        """Effect with phase=DONE stops the loop."""
        from clippy.effects.fire import FireEffect, Phase

        effect = FireEffect(seed=42)
        tick_count = [0]
        original_tick = effect.tick

        def counting_tick():
            tick_count[0] += 1
            # Safety valve: don't run forever
            if tick_count[0] > 10000:
                raise RuntimeError("loop did not stop")
            return original_tick()

        effect.tick = counting_tick

        # Give it a tiny grid so fire completes quickly
        from clippy.types import PTYUpdate
        # We override on_pty_update so the demo's call uses our small grid
        original_on_pty = effect.on_pty_update
        first_call = [True]

        def patched_on_pty(update):
            if first_call[0]:
                first_call[0] = False
                # Use 3x3 grid for fast completion
                small = PTYUpdate(size=(3, 3), cells=[], cursor=(0, 0))
                original_on_pty(small)
            else:
                original_on_pty(update)

        effect.on_pty_update = patched_on_pty

        demo_run(
            effect, 3, 3,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=lambda s: None,
            flush=lambda: None,
        )

        assert effect.phase == Phase.DONE
        assert tick_count[0] > 0

    def test_cleanup_on_writer_ioerror(self):
        """Writer IOError mid-render → cleanup still runs."""
        calls = []
        should_fail = [False]

        def writer(s):
            calls.append(s)
            if should_fail[0]:
                should_fail[0] = False
                raise IOError("write failed")

        class TriggerEffect:
            def on_pty_update(self, update): pass
            def on_resize(self, resize): pass
            def tick(self):
                should_fail[0] = True
                return [OutputCells(cells=[
                    Cell(character="X", coordinates=(0, 0),
                         fg=(1.0, 0.0, 0.0, 1.0), bg=None)
                ])]

        demo_run(
            TriggerEffect(), 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=writer,
            flush=lambda: None,
        )

        joined = "".join(calls)
        assert SHOW_CURSOR in joined
        assert ALT_SCREEN_OFF in joined

    def test_cleanup_on_flush_error(self):
        """Flush raises OSError → cleanup runs."""
        calls = []
        should_fail_flush = [False]

        def flush():
            if should_fail_flush[0]:
                should_fail_flush[0] = False
                raise OSError("flush failed")

        class TriggerEffect:
            def on_pty_update(self, update): pass
            def on_resize(self, resize): pass
            def tick(self):
                should_fail_flush[0] = True
                return [OutputCells(cells=[
                    Cell(character="X", coordinates=(0, 0),
                         fg=(1.0, 0.0, 0.0, 1.0), bg=None)
                ])]

        demo_run(
            TriggerEffect(), 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=calls.append,
            flush=flush,
        )

        joined = "".join(calls)
        assert SHOW_CURSOR in joined
        assert ALT_SCREEN_OFF in joined

    @pytest.mark.parametrize("exc_class", [KeyboardInterrupt, RuntimeError, IOError])
    def test_always_restores_terminal(self, exc_class):
        """Cleanup always runs regardless of exception type."""
        calls = []

        class ExcEffect:
            def on_pty_update(self, update): pass
            def on_resize(self, resize): pass
            def tick(self):
                raise exc_class("test")

        demo_run(
            ExcEffect(), 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=calls.append,
            flush=lambda: None,
        )

        joined = "".join(calls)
        assert SHOW_CURSOR in joined
        assert ALT_SCREEN_OFF in joined

    def test_partial_frame_failure_cleanup(self):
        """Effect works tick 1, fails tick 2 → cleanup still runs."""
        calls = []

        class PartialEffect:
            def __init__(self):
                self.tick_count = 0
            def on_pty_update(self, update): pass
            def on_resize(self, resize): pass
            def tick(self):
                self.tick_count += 1
                if self.tick_count == 1:
                    return [OutputCells(cells=[
                        Cell(character="X", coordinates=(0, 0),
                             fg=(1.0, 0.0, 0.0, 1.0), bg=None)
                    ])]
                raise RuntimeError("tick 2 failed")

        demo_run(
            PartialEffect(), 80, 24,
            fps=1000,
            clock=lambda: 0.0,
            sleep=lambda t: None,
            writer=calls.append,
            flush=lambda: None,
        )

        joined = "".join(calls)
        assert SHOW_CURSOR in joined
        assert ALT_SCREEN_OFF in joined

    def test_frame_budget_sleep(self):
        """Verify sleep is called with remaining frame budget."""
        sleep_args = []
        fake_time = [0.0]

        class TimeAdvancingEffect:
            is_done = False
            def on_pty_update(self, update):
                pass
            def on_resize(self, resize):
                pass
            def tick(self):
                # Simulate tick taking 0.01s
                fake_time[0] += 0.01
                if len(sleep_args) >= 2:
                    self.is_done = True
                return []

        def fake_sleep(timeout):
            sleep_args.append(timeout)
            fake_time[0] += timeout

        demo_run(
            TimeAdvancingEffect(), 80, 24,
            fps=30,
            clock=lambda: fake_time[0],
            sleep=fake_sleep,
            writer=lambda s: None,
            flush=lambda: None,
        )

        # frame_budget = 1/30 ≈ 0.0333, tick takes 0.01, so sleep ≈ 0.0233
        assert len(sleep_args) >= 2
        for arg in sleep_args:
            assert arg > 0
            assert arg == pytest.approx(1.0 / 30 - 0.01, abs=0.001)


# ---------------------------------------------------------------------------
# Alpha blending tests (M2)
# ---------------------------------------------------------------------------

class TestAlphaBlending:
    def test_alpha_blend_foreground(self):
        result = color_to_fg((1.0, 1.0, 1.0, 0.5))
        assert result == "\033[38;2;127;127;127m"

    def test_alpha_blend_background(self):
        result = color_to_bg((1.0, 0.0, 0.0, 0.5))
        assert result == "\033[48;2;127;0;0m"

    def test_alpha_zero_produces_black(self):
        result = color_to_fg((1.0, 1.0, 1.0, 0.0))
        assert result == "\033[38;2;0;0;0m"
