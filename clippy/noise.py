"""Pure Python 3D simplex noise — no dependencies, fully deterministic.

noise3(x, y, z) -> float in [-1.0, 1.0]

Based on Stefan Gustavson's public-domain simplex noise implementation.
"""

# Permutation table (256 entries, doubled to avoid index wrapping)
_P = [
    151, 160, 137,  91,  90,  15, 131,  13, 201,  95,  96,  53, 194, 233,   7, 225,
    140,  36, 103,  30,  69, 142,   8,  99,  37, 240,  21,  10,  23, 190,   6, 148,
    247, 120, 234,  75,   0,  26, 197,  62,  94, 252, 219, 203, 117,  35,  11,  32,
     57, 177,  33,  88, 237, 149,  56,  87, 174,  20, 125, 136, 171, 168,  68, 175,
     74, 165,  71, 134, 139,  48,  27, 166,  77, 146, 158, 231,  83, 111, 229, 122,
     60, 211, 133, 230, 220, 105,  92,  41,  55,  46, 245,  40, 244, 102, 143,  54,
     65,  25,  63, 161,   1, 216,  80,  73, 209,  76, 132, 187, 208,  89,  18, 169,
    200, 196, 135, 130, 116, 188, 159,  86, 164, 100, 109, 198, 173, 186,   3,  64,
     52, 217, 226, 250, 124, 123,   5, 202,  38, 147, 118, 126, 255,  82,  85, 212,
    207, 206,  59, 227,  47,  16,  58,  17, 182, 189,  28,  42, 223, 183, 170, 213,
    119, 248, 152,   2,  44, 154, 163,  70, 221, 153, 101, 155, 167,  43, 172,   9,
    129,  22,  39, 253,  19,  98, 108, 110,  79, 113, 224, 232, 178, 185, 112, 104,
    218, 246,  97, 228, 251,  34, 242, 193, 238, 210, 144,  12, 191, 179, 162, 241,
     81,  51, 145, 235, 249,  14, 239, 107,  49, 192, 214,  31, 181, 199, 106, 157,
    184,  84, 204, 176, 115, 121,  50,  45, 127,   4, 150, 254, 138, 236, 205,  93,
    222, 114,  67,  29,  24,  72, 243, 141, 128, 195,  78,  66, 215,  61, 156, 180,
]
_PERM = _P * 2

# 3D gradient vectors (12 edges of a cube)
_GRAD3 = [
    (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
    (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
    (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
]

_F3 = 1.0 / 3.0
_G3 = 1.0 / 6.0


def _dot3(g: tuple[int, int, int], x: float, y: float, z: float) -> float:
    return g[0] * x + g[1] * y + g[2] * z


def _noise3_python(x: float, y: float, z: float) -> float:
    """3D simplex noise. Returns a value in [-1.0, 1.0]."""
    # Skew input space to simplex cell
    s = (x + y + z) * _F3
    i = int(x + s) if (x + s) >= 0 else int(x + s) - 1
    j = int(y + s) if (y + s) >= 0 else int(y + s) - 1
    k = int(z + s) if (z + s) >= 0 else int(z + s) - 1

    t = (i + j + k) * _G3
    # Unskew simplex cell origin back to (x,y,z) space
    x0 = x - (i - t)
    y0 = y - (j - t)
    z0 = z - (k - t)

    # Determine which simplex we're in
    if x0 >= y0:
        if y0 >= z0:
            i1, j1, k1 = 1, 0, 0
            i2, j2, k2 = 1, 1, 0
        elif x0 >= z0:
            i1, j1, k1 = 1, 0, 0
            i2, j2, k2 = 1, 0, 1
        else:
            i1, j1, k1 = 0, 0, 1
            i2, j2, k2 = 1, 0, 1
    else:
        if y0 < z0:
            i1, j1, k1 = 0, 0, 1
            i2, j2, k2 = 0, 1, 1
        elif x0 < z0:
            i1, j1, k1 = 0, 1, 0
            i2, j2, k2 = 0, 1, 1
        else:
            i1, j1, k1 = 0, 1, 0
            i2, j2, k2 = 1, 1, 0

    # Offsets for remaining simplex corners
    x1 = x0 - i1 + _G3
    y1 = y0 - j1 + _G3
    z1 = z0 - k1 + _G3
    x2 = x0 - i2 + 2.0 * _G3
    y2 = y0 - j2 + 2.0 * _G3
    z2 = z0 - k2 + 2.0 * _G3
    x3 = x0 - 1.0 + 3.0 * _G3
    y3 = y0 - 1.0 + 3.0 * _G3
    z3 = z0 - 1.0 + 3.0 * _G3

    # Gradient indices
    ii = i & 255
    jj = j & 255
    kk = k & 255
    gi0 = _PERM[ii + _PERM[jj + _PERM[kk]]] % 12
    gi1 = _PERM[ii + i1 + _PERM[jj + j1 + _PERM[kk + k1]]] % 12
    gi2 = _PERM[ii + i2 + _PERM[jj + j2 + _PERM[kk + k2]]] % 12
    gi3 = _PERM[ii + 1 + _PERM[jj + 1 + _PERM[kk + 1]]] % 12

    # Corner contributions
    t0 = 0.6 - x0 * x0 - y0 * y0 - z0 * z0
    n0 = 0.0
    if t0 > 0:
        t0 *= t0
        n0 = t0 * t0 * _dot3(_GRAD3[gi0], x0, y0, z0)

    t1 = 0.6 - x1 * x1 - y1 * y1 - z1 * z1
    n1 = 0.0
    if t1 > 0:
        t1 *= t1
        n1 = t1 * t1 * _dot3(_GRAD3[gi1], x1, y1, z1)

    t2 = 0.6 - x2 * x2 - y2 * y2 - z2 * z2
    n2 = 0.0
    if t2 > 0:
        t2 *= t2
        n2 = t2 * t2 * _dot3(_GRAD3[gi2], x2, y2, z2)

    t3 = 0.6 - x3 * x3 - y3 * y3 - z3 * z3
    n3 = 0.0
    if t3 > 0:
        t3 *= t3
        n3 = t3 * t3 * _dot3(_GRAD3[gi3], x3, y3, z3)

    # Scale to [-1, 1]
    return 32.0 * (n0 + n1 + n2 + n3)


try:
    from clippy_native import noise3
except ImportError:
    noise3 = _noise3_python
