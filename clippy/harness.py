"""Effect protocol and plugin harness for tattoy.

Provides the Effect protocol, step() for deterministic testing,
and run() for the full stdin/stdout protocol loop.
"""
from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

from clippy.types import (
    OutputCells,
    OutputMessage,
    OutputPixels,
    PTYUpdate,
    TTYResize,
    from_json,
)


class Effect(Protocol):
    def on_pty_update(self, update: PTYUpdate) -> None: ...
    def on_resize(self, resize: TTYResize) -> None: ...
    def tick(self) -> list[OutputMessage]: ...
    def cancel(self) -> None: ...
    @property
    def is_done(self) -> bool: ...


def step(effect: Effect, messages: list[str]) -> list[str]:
    """Single-tick testing seam: parse messages, dispatch, tick, return JSON."""
    for raw in messages:
        msg = from_json(raw)
        if msg is None:
            continue
        if isinstance(msg, PTYUpdate):
            effect.on_pty_update(msg)
        elif isinstance(msg, TTYResize):
            effect.on_resize(msg)
    outputs = effect.tick()
    return [out.to_json() for out in outputs]


def _setup_logging(name: str) -> logging.Logger:
    """Set up file logging. NEVER writes to stdout."""
    logger = logging.getLogger(f"clippy.{name}")
    log_level = os.environ.get("CLIPPY_LOG_LEVEL", "WARNING").upper()
    logger.setLevel(getattr(logging, log_level, logging.WARNING))

    try:
        log_dir = Path.home() / ".cache" / "clippys-revenge" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(log_dir / f"clippy-{name}.log"))
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"
        ))
        logger.addHandler(handler)
    except OSError:
        pass  # Can't create log file — continue without file logging

    return logger


def _stdin_listener(
    reader,
    msg_queue: queue.Queue,
    shutdown: threading.Event,
    logger: logging.Logger,
) -> None:
    """Blocking readline loop on a daemon thread."""
    try:
        for line in reader:
            if shutdown.is_set():
                break
            stripped = line.rstrip("\n")
            if stripped:
                msg_queue.put(stripped)
    except Exception as e:
        logger.warning("stdin listener error: %s", e)
    finally:
        shutdown.set()


def run(
    effect: Effect,
    *,
    fps: int = 30,
    clock=None,
    writer=None,
    flush=None,
    reader=None,
) -> None:
    """Run the effect protocol loop.

    All parameters after effect are keyword-only testability seams.
    Defaults are resolved at runtime (not import time).
    """
    if clock is None:
        clock = time.monotonic
    if writer is None:
        writer = sys.stdout.write
    if flush is None:
        flush = sys.stdout.flush
    if reader is None:
        reader = sys.stdin

    # Get effect name for logging
    name = "unknown"
    meta = getattr(effect, "EFFECT_META", None)
    if isinstance(meta, dict):
        name = meta.get("name", name)

    logger = _setup_logging(name)

    raw_fps = os.environ.get("CLIPPY_FPS")
    if raw_fps is not None:
        try:
            fps = int(raw_fps)
        except ValueError:
            logger.warning("Invalid CLIPPY_FPS=%r, using default %d", raw_fps, fps)
    fps = max(1, fps)
    frame_budget = 1.0 / fps

    shutdown = threading.Event()
    msg_queue: queue.Queue = queue.Queue()

    def _handle_sigterm(signum, frame):
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    listener = threading.Thread(
        target=_stdin_listener,
        args=(reader, msg_queue, shutdown, logger),
        daemon=True,
    )
    listener.start()

    def _drain_and_dispatch():
        while True:
            try:
                raw = msg_queue.get_nowait()
            except queue.Empty:
                break
            msg = from_json(raw)
            if msg is None:
                logger.debug("Skipping malformed message: %s", raw[:100])
                continue
            try:
                if isinstance(msg, PTYUpdate):
                    effect.on_pty_update(msg)
                elif isinstance(msg, TTYResize):
                    effect.on_resize(msg)
            except Exception:
                logger.exception("Effect callback error")

    # Track last output type so we can send a one-shot clear when an effect
    # goes quiet — otherwise tattoy keeps re-compositing the last frame.
    _last_output_type: type | None = None

    try:
        while not shutdown.is_set():
            frame_start = clock()

            _drain_and_dispatch()

            try:
                outputs = effect.tick()
            except Exception:
                logger.exception("Effect tick error")
                outputs = []

            if outputs:
                _last_output_type = type(outputs[0])
                write_outputs: list[OutputMessage] = outputs
            elif _last_output_type is not None:
                # Effect just went quiet — send one clear frame to wipe the layer.
                if _last_output_type is OutputCells:
                    write_outputs = [OutputCells(cells=[])]
                elif _last_output_type is OutputPixels:
                    write_outputs = [OutputPixels(pixels=[])]
                else:
                    write_outputs = []
                _last_output_type = None
            else:
                write_outputs = []

            if write_outputs:
                try:
                    for out in write_outputs:
                        writer(out.to_json() + "\n")
                    flush()
                except (BrokenPipeError, OSError):
                    logger.debug("Output pipe broken, shutting down")
                    shutdown.set()
                except Exception:
                    logger.exception("Error serializing/writing output")

            elapsed = clock() - frame_start
            remaining = frame_budget - elapsed
            if remaining > 0:
                shutdown.wait(timeout=remaining)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        listener.join(timeout=0.1)
        # Final drain: process any messages queued before shutdown
        _drain_and_dispatch()
