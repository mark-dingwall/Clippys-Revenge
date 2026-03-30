#!/usr/bin/env python3
"""Launch the test_blank_plugin in tattoy for visual diagnosis.

Usage: python3 tools/run_test_plugin.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, project_root)

from clippy.launcher import find_tattoy, generate_config, ensure_executable

tattoy_path = find_tattoy()
if tattoy_path is None:
    print("Error: tattoy not found. Install from https://tattoy.sh", file=sys.stderr)
    sys.exit(1)

plugin_path = str(Path(__file__).resolve().parent / "test_blank_plugin.py")
ensure_executable(Path(plugin_path))

# Set PYTHONPATH for the subprocess
existing = os.environ.get("PYTHONPATH", "")
if project_root not in existing.split(os.pathsep):
    os.environ["PYTHONPATH"] = project_root + (os.pathsep + existing if existing else "")

config_path = generate_config(
    effect_paths=[plugin_path],
    fps=30,
)

print("Launching tattoy with test plugin...")
print()
print("Look at your terminal and note:")
print("  TEST 1 (rows 0-2): Red A's flash, then only (0,0) becomes green B")
print("    → Red A's STAY visible = RETAIN semantics")
print("    → Red A's VANISH       = REPLACE semantics")
print()
print("  TEST 2 (rows 4-6): Space with bg=null")
print("    → Terminal text HIDDEN  = bg=null is opaque")
print("    → Terminal text VISIBLE = bg=null is transparent")
print()
print("  TEST 3 (rows 8-10): Space with opaque black bg")
print("    → Terminal text HIDDEN  = opaque bg works")
print("    → Terminal text VISIBLE = layer rendering is broken")
print()

os.execvp(tattoy_path, [tattoy_path, "--config-dir", config_path])
