use pyo3::prelude::*;
use pyo3::types::PyList;
use std::fmt::Write as FmtWrite;

// ---------------------------------------------------------------------------
// Character escape table (matches Python _CHAR_TABLE)
// ---------------------------------------------------------------------------

const fn build_char_table() -> [&'static str; 128] {
    let mut table: [&str; 128] = [""; 128];
    let mut i: u8 = 0;
    loop {
        if i >= 128 {
            break;
        }
        table[i as usize] = match i {
            b'"' => "\\\"",
            b'\\' => "\\\\",
            b'\n' => "\\n",
            b'\r' => "\\r",
            b'\t' => "\\t",
            0x00 => "\\u0000",
            0x01 => "\\u0001",
            0x02 => "\\u0002",
            0x03 => "\\u0003",
            0x04 => "\\u0004",
            0x05 => "\\u0005",
            0x06 => "\\u0006",
            0x07 => "\\u0007",
            0x08 => "\\u0008",
            0x0b => "\\u000b",
            0x0c => "\\u000c",
            0x0e => "\\u000e",
            0x0f => "\\u000f",
            0x10 => "\\u0010",
            0x11 => "\\u0011",
            0x12 => "\\u0012",
            0x13 => "\\u0013",
            0x14 => "\\u0014",
            0x15 => "\\u0015",
            0x16 => "\\u0016",
            0x17 => "\\u0017",
            0x18 => "\\u0018",
            0x19 => "\\u0019",
            0x1a => "\\u001a",
            0x1b => "\\u001b",
            0x1c => "\\u001c",
            0x1d => "\\u001d",
            0x1e => "\\u001e",
            0x1f => "\\u001f",
            _ => "", // filled below for printable ASCII
        };
        i += 1;
    }
    table
}

static CHAR_TABLE: [&str; 128] = build_char_table();

/// Write a JSON-escaped character into the buffer.
fn write_json_char(buf: &mut String, ch: char) {
    let code = ch as u32;
    if code < 128 {
        let entry = CHAR_TABLE[code as usize];
        if !entry.is_empty() {
            buf.push_str(entry);
        } else {
            // Printable ASCII not in the special table
            buf.push(ch);
        }
    } else {
        // Non-ASCII: pass through unchanged (same as Python)
        buf.push(ch);
    }
}

/// Format an f64 using ryu (shortest round-trip representation).
fn write_f64(buf: &mut String, v: f64) {
    // Handle common exact values without ryu for cleaner output
    if v == 0.0 {
        buf.push_str("0.0");
    } else if v == 1.0 {
        buf.push_str("1.0");
    } else {
        let mut ryu_buf = ryu::Buffer::new();
        let s = ryu_buf.format(v);
        buf.push_str(s);
        // ryu may produce "0.5" without trailing zero — that's fine for JSON
        // but Python produces "0.5" too, so this matches
    }
}

/// Write a color tuple as JSON array, or "null".
fn write_color(buf: &mut String, color: Option<(f64, f64, f64, f64)>) {
    match color {
        Some((r, g, b, a)) => {
            buf.push('[');
            write_f64(buf, r);
            buf.push_str(", ");
            write_f64(buf, g);
            buf.push_str(", ");
            write_f64(buf, b);
            buf.push_str(", ");
            write_f64(buf, a);
            buf.push(']');
        }
        None => buf.push_str("null"),
    }
}

/// Extract an optional RGBA color tuple from a Python object.
fn extract_color(obj: &Bound<'_, PyAny>) -> PyResult<Option<(f64, f64, f64, f64)>> {
    if obj.is_none() {
        Ok(None)
    } else {
        let tup: (f64, f64, f64, f64) = obj.extract()?;
        Ok(Some(tup))
    }
}

// ---------------------------------------------------------------------------
// P0: JSON serialization
// ---------------------------------------------------------------------------

/// Serialize a list of Cell dataclass instances to JSON (output_cells wire format).
#[pyfunction]
fn serialize_cells(cells: &Bound<'_, PyList>) -> PyResult<String> {
    let len = cells.len();
    // Pre-allocate: ~80 bytes per cell is a reasonable estimate
    let mut buf = String::with_capacity(20 + len * 80);
    buf.push_str("{\"output_cells\": [");

    for (i, cell) in cells.iter().enumerate() {
        if i > 0 {
            buf.push_str(", ");
        }
        // Extract fields via attribute access on the Python dataclass
        let character: String = cell.getattr("character")?.extract()?;
        let coords: (i64, i64) = cell.getattr("coordinates")?.extract()?;
        let fg_obj = cell.getattr("fg")?;
        let bg_obj = cell.getattr("bg")?;
        let fg = extract_color(&fg_obj)?;
        let bg = extract_color(&bg_obj)?;

        buf.push_str("{\"character\": \"");
        // Escape the character (typically single char, but handle multi-char)
        for ch in character.chars() {
            write_json_char(&mut buf, ch);
        }
        buf.push_str("\", \"coordinates\": [");
        let _ = write!(buf, "{}, {}", coords.0, coords.1);
        buf.push_str("], \"fg\": ");
        write_color(&mut buf, fg);
        buf.push_str(", \"bg\": ");
        write_color(&mut buf, bg);
        buf.push('}');
    }

    buf.push_str("]}");
    Ok(buf)
}

/// Serialize a list of Pixel dataclass instances to JSON (output_pixels wire format).
#[pyfunction]
fn serialize_pixels(pixels: &Bound<'_, PyList>) -> PyResult<String> {
    let len = pixels.len();
    let mut buf = String::with_capacity(20 + len * 60);
    buf.push_str("{\"output_pixels\": [");

    for (i, pixel) in pixels.iter().enumerate() {
        if i > 0 {
            buf.push_str(", ");
        }
        let coords: (i64, i64) = pixel.getattr("coordinates")?.extract()?;
        let color_obj = pixel.getattr("color")?;
        let color = extract_color(&color_obj)?;

        buf.push_str("{\"coordinates\": [");
        let _ = write!(buf, "{}, {}", coords.0, coords.1);
        buf.push_str("], \"color\": ");
        write_color(&mut buf, color);
        buf.push('}');
    }

    buf.push_str("]}");
    Ok(buf)
}

// ---------------------------------------------------------------------------
// P1: Color math
// ---------------------------------------------------------------------------

/// Dim a color by a factor, preserving alpha. Equivalent to _dim_color / _tint.
#[pyfunction]
fn tint_color(color: (f64, f64, f64, f64), factor: f64) -> (f64, f64, f64, f64) {
    (color.0 * factor, color.1 * factor, color.2 * factor, color.3)
}

/// Adjust the alpha of a color. Equivalent to _fade_color.
#[pyfunction]
fn fade_color(color: (f64, f64, f64, f64), alpha: f64) -> (f64, f64, f64, f64) {
    (color.0, color.1, color.2, color.3 * alpha)
}

// ---------------------------------------------------------------------------
// P1: Simplex noise
// ---------------------------------------------------------------------------

static PERM: [u8; 512] = {
    let p: [u8; 256] = [
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
    ];
    let mut table = [0u8; 512];
    let mut i = 0;
    while i < 512 {
        table[i] = p[i % 256];
        i += 1;
    }
    table
};

static GRAD3: [(f64, f64, f64); 12] = [
    ( 1.0,  1.0,  0.0), (-1.0,  1.0,  0.0), ( 1.0, -1.0,  0.0), (-1.0, -1.0,  0.0),
    ( 1.0,  0.0,  1.0), (-1.0,  0.0,  1.0), ( 1.0,  0.0, -1.0), (-1.0,  0.0, -1.0),
    ( 0.0,  1.0,  1.0), ( 0.0, -1.0,  1.0), ( 0.0,  1.0, -1.0), ( 0.0, -1.0, -1.0),
];

const F3: f64 = 1.0 / 3.0;
const G3: f64 = 1.0 / 6.0;

#[inline]
fn dot3(g: (f64, f64, f64), x: f64, y: f64, z: f64) -> f64 {
    g.0 * x + g.1 * y + g.2 * z
}

/// 3D simplex noise. Returns a value in [-1.0, 1.0].
#[pyfunction]
fn noise3(x: f64, y: f64, z: f64) -> f64 {
    let s = (x + y + z) * F3;
    let i = (x + s).floor() as i64;
    let j = (y + s).floor() as i64;
    let k = (z + s).floor() as i64;

    let t = (i + j + k) as f64 * G3;
    let x0 = x - (i as f64 - t);
    let y0 = y - (j as f64 - t);
    let z0 = z - (k as f64 - t);

    let (i1, j1, k1, i2, j2, k2);
    if x0 >= y0 {
        if y0 >= z0 {
            i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0;
        } else if x0 >= z0 {
            i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1;
        } else {
            i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1;
        }
    } else {
        if y0 < z0 {
            i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1;
        } else if x0 < z0 {
            i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1;
        } else {
            i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0;
        }
    }

    let x1 = x0 - i1 as f64 + G3;
    let y1 = y0 - j1 as f64 + G3;
    let z1 = z0 - k1 as f64 + G3;
    let x2 = x0 - i2 as f64 + 2.0 * G3;
    let y2 = y0 - j2 as f64 + 2.0 * G3;
    let z2 = z0 - k2 as f64 + 2.0 * G3;
    let x3 = x0 - 1.0 + 3.0 * G3;
    let y3 = y0 - 1.0 + 3.0 * G3;
    let z3 = z0 - 1.0 + 3.0 * G3;

    let ii = (i & 255) as usize;
    let jj = (j & 255) as usize;
    let kk = (k & 255) as usize;
    let gi0 = PERM[ii + PERM[jj + PERM[kk] as usize] as usize] as usize % 12;
    let gi1 = PERM[ii + i1 + PERM[jj + j1 + PERM[kk + k1] as usize] as usize] as usize % 12;
    let gi2 = PERM[ii + i2 + PERM[jj + j2 + PERM[kk + k2] as usize] as usize] as usize % 12;
    let gi3 = PERM[ii + 1 + PERM[jj + 1 + PERM[kk + 1] as usize] as usize] as usize % 12;

    let mut t0 = 0.6 - x0 * x0 - y0 * y0 - z0 * z0;
    let n0 = if t0 > 0.0 {
        t0 *= t0;
        t0 * t0 * dot3(GRAD3[gi0], x0, y0, z0)
    } else {
        0.0
    };

    let mut t1 = 0.6 - x1 * x1 - y1 * y1 - z1 * z1;
    let n1 = if t1 > 0.0 {
        t1 *= t1;
        t1 * t1 * dot3(GRAD3[gi1], x1, y1, z1)
    } else {
        0.0
    };

    let mut t2 = 0.6 - x2 * x2 - y2 * y2 - z2 * z2;
    let n2 = if t2 > 0.0 {
        t2 *= t2;
        t2 * t2 * dot3(GRAD3[gi2], x2, y2, z2)
    } else {
        0.0
    };

    let mut t3 = 0.6 - x3 * x3 - y3 * y3 - z3 * z3;
    let n3 = if t3 > 0.0 {
        t3 *= t3;
        t3 * t3 * dot3(GRAD3[gi3], x3, y3, z3)
    } else {
        0.0
    };

    32.0 * (n0 + n1 + n2 + n3)
}

// ---------------------------------------------------------------------------
// P2: Heat computation (DOOM fire)
// ---------------------------------------------------------------------------

/// Compute DOOM-fire heat propagation on flat arrays.
///
/// Arguments:
///   heat_flat       — row-major f64 grid (width * height), modified in-place
///   is_hot_flat     — row-major bool grid, modified in-place
///   old_hot_list    — (x, y) pairs that were hot last frame (to zero)
///   burning_positions — (x, y) pairs of currently burning cells
///   ignition_tick_flat — row-major i64 grid of ignition ticks
///   cell_state_flat — row-major i32 grid of cell states
///   tick_count      — current tick
///   width, height   — grid dimensions
///   burn_duration   — BURN_DURATION constant
///   heat_decay_max  — HEAT_DECAY_MAX constant
///   drift_vals      — pre-generated randint(-1,1) values
///   decay_vals      — pre-generated random() * HEAT_DECAY_MAX values
///   min_x, max_x, min_y, max_y — bounding box of burning positions
///
/// Returns: (heat_flat, is_hot_flat, hot_list, shimmer_cells)
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn compute_heat(
    mut heat_flat: Vec<f64>,
    mut is_hot_flat: Vec<bool>,
    old_hot_list: Vec<(usize, usize)>,
    burning_positions: Vec<(usize, usize)>,
    ignition_tick_flat: Vec<i64>,
    cell_state_flat: Vec<i32>,
    tick_count: i64,
    width: usize,
    _height: usize,
    burn_duration: i64,
    _heat_decay_max: f64,
    drift_vals: Vec<i32>,
    decay_vals: Vec<f64>,
    min_x: usize,
    max_x: usize,
    min_y: usize,
    max_y: usize,
) -> (Vec<f64>, Vec<bool>, Vec<(usize, usize)>, Vec<(usize, usize)>) {
    const CLEAR: i32 = 0;

    // Zero cells that were hot last frame
    for &(x, y) in &old_hot_list {
        let idx = y * width + x;
        heat_flat[idx] = 0.0;
        is_hot_flat[idx] = false;
    }

    let mut hot_list: Vec<(usize, usize)> = Vec::new();
    let mut shimmer: Vec<(usize, usize)> = Vec::new();

    if burning_positions.is_empty() {
        return (heat_flat, is_hot_flat, hot_list, shimmer);
    }

    // Seed BURNING cells
    for &(x, y) in &burning_positions {
        let idx = y * width + x;
        let age = tick_count - ignition_tick_flat[idx];
        let ratio = if burn_duration > 0 {
            age as f64 / burn_duration as f64
        } else {
            1.0
        };
        let heat_val = if ratio < 0.3 {
            1.0
        } else if ratio < 0.7 {
            0.7
        } else {
            0.4
        };
        heat_flat[idx] = heat_val;
        is_hot_flat[idx] = true;
        hot_list.push((x, y));
    }

    // Propagate upward within bounding box
    let margin: usize = 15;
    let col_lo = min_x.saturating_sub(margin);
    let col_hi = (max_x + margin + 1).min(width);
    let row_top = min_y.saturating_sub(margin);

    let mut rng_idx: usize = 0;

    for y in (row_top..max_y).rev() {
        let mut any_heat = false;

        // Even columns: full propagation with pre-generated RNG
        let even_start = col_lo & !1;
        let mut x = even_start;
        while x < col_hi {
            let drift = drift_vals[rng_idx % drift_vals.len()];
            let decay = decay_vals[rng_idx % decay_vals.len()];
            rng_idx += 1;

            let src_x = (x as i64 + drift as i64).max(0).min(width as i64 - 1) as usize;
            let cur_idx = y * width + x;
            let below_idx = (y + 1) * width + src_x;
            let val = heat_flat[cur_idx].max(heat_flat[below_idx] - decay);

            if val > 0.0 {
                heat_flat[cur_idx] = val;
                if !is_hot_flat[cur_idx] {
                    is_hot_flat[cur_idx] = true;
                    hot_list.push((x, y));
                }
                if val > 0.02 && cell_state_flat[cur_idx] == CLEAR {
                    shimmer.push((x, y));
                }
                any_heat = true;
            }
            x += 2;
        }

        // Odd columns: nearest-neighbor fill, alternating direction
        let odd_start = col_lo | 1;
        let mut x = odd_start;
        while x < col_hi {
            let val = if y % 2 == 0 {
                if x > 0 { heat_flat[y * width + x - 1] } else { 0.0 }
            } else {
                if x + 1 < width { heat_flat[y * width + x + 1] } else { 0.0 }
            };

            if val > 0.0 {
                let cur_idx = y * width + x;
                heat_flat[cur_idx] = val;
                if !is_hot_flat[cur_idx] {
                    is_hot_flat[cur_idx] = true;
                    hot_list.push((x, y));
                }
                if val > 0.02 && cell_state_flat[cur_idx] == CLEAR {
                    shimmer.push((x, y));
                }
                any_heat = true;
            }
            x += 2;
        }

        if !any_heat {
            break;
        }
    }

    (heat_flat, is_hot_flat, hot_list, shimmer)
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

/// Return the version of the native extension module.
#[pyfunction]
fn native_version() -> &'static str {
    "0.1.0"
}

/// clippy_native — optional Rust acceleration for Clippy's Revenge.
#[pymodule]
fn clippy_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(native_version, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_cells, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_pixels, m)?)?;
    m.add_function(wrap_pyfunction!(tint_color, m)?)?;
    m.add_function(wrap_pyfunction!(fade_color, m)?)?;
    m.add_function(wrap_pyfunction!(noise3, m)?)?;
    m.add_function(wrap_pyfunction!(compute_heat, m)?)?;
    Ok(())
}
