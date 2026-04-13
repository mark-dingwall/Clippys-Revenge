"""Tests for clippy.noise — 3D simplex noise."""
import pytest

from clippy.noise import noise3


def test_noise3_deterministic():
    """Same inputs always produce the same output."""
    a = noise3(1.5, 2.3, 0.7)
    b = noise3(1.5, 2.3, 0.7)
    assert a == b


def test_noise3_range():
    """Output is bounded to [-1.0, 1.0] across a broad sample of inputs."""
    import itertools
    coords = [-10.0, -1.0, 0.0, 0.5, 1.0, 3.7, 10.0]
    for x, y, z in itertools.product(coords, repeat=3):
        val = noise3(x, y, z)
        assert -1.0 <= val <= 1.0, f"noise3({x}, {y}, {z}) = {val} out of [-1, 1]"


def test_noise3_gradient_continuity():
    """Nearby points differ by < 0.1 — confirms continuous function."""
    base = noise3(5.0, 3.0, 1.0)
    delta = 0.001
    for dx, dy, dz in [(delta, 0, 0), (0, delta, 0), (0, 0, delta)]:
        nearby = noise3(5.0 + dx, 3.0 + dy, 1.0 + dz)
        assert abs(nearby - base) < 0.1, (
            f"Discontinuity: base={base}, nearby={nearby}, diff={abs(nearby - base)}"
        )


def test_noise3_variation():
    """Multiple distinct inputs produce multiple distinct outputs."""
    values = {noise3(x * 1.7, x * 2.3, x * 0.9) for x in range(20)}
    assert len(values) > 10, f"Only {len(values)} distinct values from 20 inputs"


def test_noise3_negative_coordinates():
    """Negative coordinates: in range + deterministic."""
    a = noise3(-5.5, -3.2, -1.7)
    b = noise3(-5.5, -3.2, -1.7)
    assert a == b
    assert -1.0 <= a <= 1.0


def test_noise3_large_coordinates():
    """Large coordinates: in range, no crash — exercises & 255 masking."""
    val = noise3(1e6, 1e6, 1e6)
    assert -1.0 <= val <= 1.0


def test_noise3_integer_boundaries():
    """Values at floor transition points are in range."""
    for x in [0.0, 1.0, -1.0, 0.999999, 1.000001]:
        val = noise3(x, x, x)
        assert -1.0 <= val <= 1.0, f"noise3({x}, {x}, {x}) = {val}"


def test_noise3_python_fallback_matches():
    """_noise3_python matches noise3 — verifies fallback parity."""
    from clippy.noise import _noise3_python
    for x, y, z in [(1.5, 2.3, 0.7), (-1.0, 0.0, 3.5), (100.0, 200.0, 300.0)]:
        assert _noise3_python(x, y, z) == noise3(x, y, z)
