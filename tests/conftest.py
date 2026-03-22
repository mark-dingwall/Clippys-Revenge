"""Shared pytest fixtures for Clippy's Revenge tests."""
import io
from pathlib import Path

import pytest


@pytest.fixture
def sample_pty_update_json():
    return '{"pty_update": {"size": [80, 24], "cells": [{"character": "A", "coordinates": [0, 0], "fg": [1.0, 1.0, 1.0, 1.0], "bg": [0.0, 0.0, 0.0, 1.0]}]}}'


@pytest.fixture
def sample_tty_resize_json():
    return '{"tty_resize": {"width": 120, "height": 40}}'


@pytest.fixture
def fake_stdin():
    """Pre-loaded stdin replacement. Write messages then seek(0) before use."""
    buf = io.StringIO()
    yield buf


@pytest.fixture
def captured_stdout():
    """Captures harness stdout output for assertion."""
    lines = []

    def writer(line):
        lines.append(line)

    writer.lines = lines
    return writer


@pytest.fixture
def stub_effect():
    """Minimal Effect implementation that records all callbacks."""
    from clippy.types import OutputText

    class StubEffect:
        def __init__(self):
            self.updates = []
            self.resizes = []
            self._done = False

        def on_pty_update(self, update):
            self.updates.append(update)

        def on_resize(self, resize):
            self.resizes.append(resize)

        def tick(self):
            return [OutputText(
                text="stub",
                coordinates=(0, 0),
                fg=(1.0, 1.0, 1.0, 1.0),
                bg=None,
            )]

        def cancel(self):
            self._done = True

        @property
        def is_done(self):
            return self._done

    return StubEffect()


@pytest.fixture
def golden_dir():
    return Path(__file__).parent / "golden"
