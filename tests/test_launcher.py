"""Tests for effect discovery and the clippy launcher CLI."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from clippy.effects import discover_effects
from clippy.launcher import (
    _escape_toml_string,
    _parse_effect_names,
    ensure_executable,
    find_tattoy,
    generate_config,
    main,
)


# ---------------------------------------------------------------------------
# Effect discovery
# ---------------------------------------------------------------------------

class TestDiscoverEffects:
    def test_discovers_fire(self):
        effects = discover_effects()
        assert "fire" in effects

    def test_meta_structure(self):
        meta = discover_effects()["fire"]
        assert meta["name"] == "fire"
        assert meta["class_name"] == "FireEffect"
        assert Path(meta["module_path"]).is_absolute()
        assert Path(meta["module_path"]).is_file()

    def test_excludes_init(self):
        for meta in discover_effects().values():
            assert not meta["module_path"].endswith("__init__.py")


# ---------------------------------------------------------------------------
# find_tattoy
# ---------------------------------------------------------------------------

class TestFindTattoy:
    def test_found_on_path(self):
        with mock.patch("shutil.which", return_value="/usr/bin/tattoy"):
            assert find_tattoy() == "/usr/bin/tattoy"

    def test_found_in_cargo(self, tmp_path):
        cargo_bin = tmp_path / ".cargo" / "bin"
        cargo_bin.mkdir(parents=True)
        fake = cargo_bin / "tattoy"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)

        with mock.patch("shutil.which", return_value=None), \
             mock.patch("pathlib.Path.home", return_value=tmp_path):
            result = find_tattoy()
        assert result is not None
        assert result.endswith("tattoy")

    def test_not_found(self, tmp_path):
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("pathlib.Path.home", return_value=tmp_path):
            assert find_tattoy() is None


# ---------------------------------------------------------------------------
# ensure_executable
# ---------------------------------------------------------------------------

class TestEnsureExecutable:
    def test_adds_shebang(self, tmp_path):
        script = tmp_path / "test.py"
        script.write_text('"""docstring"""\nimport sys\n')
        ensure_executable(script)
        assert script.read_text().startswith("#!/usr/bin/env python3\n")
        assert '"""docstring"""' in script.read_text()

    def test_preserves_existing_shebang(self, tmp_path):
        script = tmp_path / "test.py"
        script.write_text("#!/usr/bin/env python3\nimport sys\n")
        ensure_executable(script)
        assert script.read_text().count("#!/usr/bin/env python3") == 1

    def test_sets_executable(self, tmp_path):
        script = tmp_path / "test.py"
        script.write_text("#!/usr/bin/env python3\n")
        script.chmod(0o644)
        ensure_executable(script)
        assert script.stat().st_mode & stat.S_IXUSR


# ---------------------------------------------------------------------------
# generate_config
# ---------------------------------------------------------------------------

class TestGenerateConfig:
    def test_creates_dir(self, tmp_path):
        config_dir = generate_config(["/path/to/fire.py"], config_dir=str(tmp_path / "cfg"))
        assert Path(config_dir).is_dir()
        assert (Path(config_dir) / "tattoy.toml").is_file()

    def test_toml_content(self, tmp_path):
        config_dir = generate_config(
            ["/path/to/fire.py"],
            shell_cmd="/bin/zsh",
            config_dir=str(tmp_path),
        )
        content = (Path(config_dir) / "tattoy.toml").read_text()
        assert 'command = "/bin/zsh"' in content
        assert "frame_rate = 30" in content
        assert 'path = "/path/to/fire.py"' in content
        assert "[[plugins]]" in content
        assert 'name = "fire"' in content
        assert "layer = 1" in content
        assert "show_tattoy_indicator = false" in content
        assert "show_startup_logo = false" in content
        assert "[keybindings]" in content
        assert 'toggle_tattoy' in content

    def test_seeds_palette(self, tmp_path):
        config_dir = generate_config(["/path/to/fire.py"], config_dir=str(tmp_path))
        assert (Path(config_dir) / "palette.toml").is_file()

    def test_does_not_overwrite_existing_palette(self, tmp_path):
        existing = tmp_path / "palette.toml"
        existing.write_text("custom = [1, 2, 3]\n")
        generate_config(["/path/to/fire.py"], config_dir=str(tmp_path))
        assert existing.read_text() == "custom = [1, 2, 3]\n"

    def test_default_shell(self, tmp_path):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/fish"}):
            config_dir = generate_config(["/path/to/fire.py"], config_dir=str(tmp_path))
        content = (Path(config_dir) / "tattoy.toml").read_text()
        assert 'command = "/bin/fish"' in content

    def test_backslash_escaping(self, tmp_path):
        config_dir = generate_config(
            [r"C:\Users\test\fire.py"],
            shell_cmd=r"C:\Windows\system32\cmd.exe",
            config_dir=str(tmp_path),
        )
        content = (Path(config_dir) / "tattoy.toml").read_text()
        assert r'command = "C:\\Windows\\system32\\cmd.exe"' in content
        assert r'path = "C:\\Users\\test\\fire.py"' in content

    def test_quote_escaping(self, tmp_path):
        config_dir = generate_config(
            ['/path/to/"fire".py'],
            shell_cmd='/bin/sh -c "echo hi"',
            config_dir=str(tmp_path),
        )
        content = (Path(config_dir) / "tattoy.toml").read_text()
        assert r'command = "/bin/sh -c \"echo hi\""' in content
        assert r'path = "/path/to/\"fire\".py"' in content

    def test_multiple_effects_each_get_plugin_block(self, tmp_path):
        config_dir = generate_config(
            ["/path/to/fire.py", "/path/to/grove.py"],
            config_dir=str(tmp_path),
        )
        content = (Path(config_dir) / "tattoy.toml").read_text()
        assert content.count("[[plugins]]") == 2
        assert 'name = "fire"' in content
        assert 'name = "grove"' in content


# ---------------------------------------------------------------------------
# CLI integration (main)
# ---------------------------------------------------------------------------

class TestMain:
    def test_help_shows_clippy(self, capsys):
        with pytest.raises(SystemExit, match="0"):
            main(["--help"])
        out = capsys.readouterr().out
        assert "It looks like" in out
        assert "^╭╮^" in out
        assert "--effects" in out

    def test_list_effects(self, capsys):
        assert main(["--list"]) == 0
        out = capsys.readouterr().out
        assert "fire" in out
        assert "It looks like" in out
        assert "^╭╮^" in out

    def test_list_empty(self, capsys):
        with mock.patch("clippy.effects.discover_effects", return_value={}):
            assert main(["--list"]) == 0
        assert "No effects" in capsys.readouterr().out

    def test_effects_all_invalid(self, capsys):
        assert main(["--effects", "bogus"]) == 1
        err = capsys.readouterr().err
        assert "It looks like" in err
        assert "^╭╮^" in err

    def test_demo_runs(self):
        with mock.patch("clippy.demo.demo_run") as mock_demo:
            assert main(["--demo", "fire"]) == 0
        mock_demo.assert_called_once()

    def test_demo_unknown(self, capsys):
        assert main(["--demo", "nonexistent"]) == 1
        err = capsys.readouterr().err
        assert "It looks like" in err

    def test_no_tattoy(self, capsys):
        with mock.patch("clippy.launcher.find_tattoy", return_value=None), \
             mock.patch("clippy.launcher._try_build_native", return_value=False):
            assert main(["--effects", "fire"]) == 1
        captured = capsys.readouterr()
        assert "tattoy not found" in captured.err
        assert "It looks like" in captured.err

    def test_launch_execs_tattoy(self, tmp_path):
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp") as mock_exec:
            main(["--effects", "fire"])

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/bin/tattoy"
        assert "--config-dir" in args[1]
        assert "/tmp/test.toml" in args[1]

    def test_command_passthrough(self):
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml") as mock_gen, \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", "fire", "--", "vim", "file.txt"])

        _, kwargs = mock_gen.call_args
        assert kwargs["shell_cmd"] == "vim file.txt"

    def test_no_effects_exits_1(self, capsys):
        with mock.patch("clippy.effects.discover_effects", return_value={}):
            assert main([]) == 1
        assert "No effects" in capsys.readouterr().err

    def test_list_excludes_overlay(self, capsys):
        fake_effects = {
            "fire": {"name": "fire", "description": "Fire", "module_path": "/fire.py", "class_name": "FireEffect"},
            "mascot": {"name": "mascot", "description": "Mascot", "overlay": True, "module_path": "/mascot.py", "class_name": "MascotEffect"},
        }
        with mock.patch("clippy.effects.discover_effects", return_value=fake_effects):
            assert main(["--list"]) == 0
        out = capsys.readouterr().out
        assert "fire" in out
        assert "mascot" not in out

    def test_effects_overlay_rejected(self, capsys):
        assert main(["--effects", "mascot"]) == 1
        err = capsys.readouterr().err
        assert "overlay" in err.lower()
        assert "It looks like" in err

    def test_demo_overlay_allowed(self):
        with mock.patch("clippy.demo.demo_run"):
            assert main(["--demo", "mascot"]) == 0

    def test_launch_uses_unified_runner(self):
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml") as mock_gen, \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", "fire"])
        _, kwargs = mock_gen.call_args
        assert len(kwargs["effect_paths"]) == 1
        assert "unified_runner" in kwargs["effect_paths"][0]

    def test_no_effects_flag_does_not_set_env(self):
        """When no --effects flag, CLIPPY_EFFECTS is NOT set in env."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            os.environ["CLIPPY_EFFECTS"] = "stale"
            os.environ["CLIPPY_EFFECT"] = "stale"
            main([])

        assert "CLIPPY_EFFECTS" not in os.environ
        assert "CLIPPY_EFFECT" not in os.environ

    def test_effects_flag_sets_env(self):
        """--effects fire sets CLIPPY_EFFECTS=fire in env."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", "fire"])

        assert os.environ.get("CLIPPY_EFFECTS") == "fire"

    def test_effects_comma_separated(self):
        """--effects fire,grove sets CLIPPY_EFFECTS=fire,grove."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", "fire,grove"])

        assert os.environ.get("CLIPPY_EFFECTS") == "fire,grove"

    def test_effects_deduplicates(self):
        """--effects fire,fire,grove deduplicates to fire,grove."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", "fire,fire,grove"])

        assert os.environ.get("CLIPPY_EFFECTS") == "fire,grove"

    def test_effects_strips_whitespace(self):
        """--effects ' fire , grove ' strips whitespace."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", " fire , grove "])

        assert os.environ.get("CLIPPY_EFFECTS") == "fire,grove"

    def test_effects_partial_invalid(self, capsys):
        """--effects fire,bogus warns but continues with fire only."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            result = main(["--effects", "fire,bogus"])

        assert result == 0
        assert os.environ.get("CLIPPY_EFFECTS") == "fire"
        err = capsys.readouterr().err
        assert "Ignoring unknown" in err

    def test_optimised_off(self):
        """--optimised off skips native build."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch("clippy.launcher._try_build_native") as mock_build, \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            main(["--effects", "fire", "--optimised", "off"])

        mock_build.assert_not_called()

    def test_optimised_on_success(self):
        """--optimised on with native available proceeds."""
        with mock.patch("clippy.launcher.find_tattoy", return_value="/usr/bin/tattoy"), \
             mock.patch("clippy.launcher.generate_config", return_value="/tmp/test.toml"), \
             mock.patch("clippy.launcher.ensure_executable"), \
             mock.patch.dict("sys.modules", {"clippy_native": mock.MagicMock()}), \
             mock.patch("time.sleep"), \
             mock.patch("os.execvp"):
            result = main(["--effects", "fire", "--optimised", "on"])

        assert result == 0

    def test_optimised_on_missing(self, capsys):
        """--optimised on with native unavailable exits 1 with instructions."""
        with mock.patch.dict("sys.modules", {"clippy_native": None}):
            result = main(["--effects", "fire", "--optimised", "on"])

        assert result == 1
        err = capsys.readouterr().err
        assert "It looks like" in err
        assert "maturin" in err


# ---------------------------------------------------------------------------
# Theme CLI flags
# ---------------------------------------------------------------------------

class TestThemeCLI:
    def test_theme_reset(self, capsys, tmp_path):
        with mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            result = main(["--theme-reset"])
        assert result == 0
        out = capsys.readouterr().out
        assert "Tokyo Night" in out

    def test_theme_apply_known(self):
        with mock.patch("clippy.themes.find_theme") as mock_find, \
             mock.patch("clippy.themes.apply_theme") as mock_apply, \
             mock.patch("clippy.demo.demo_run"):
            from clippy.themes import default_theme
            mock_find.return_value = default_theme()
            result = main(["--theme", "Tokyo Night", "--demo", "fire"])
        assert result == 0
        mock_apply.assert_called_once()

    def test_theme_unknown(self, capsys):
        with mock.patch("clippy.themes.find_theme", return_value=None), \
             mock.patch("clippy.themes.load_all_themes", return_value=[]):
            result = main(["--theme", "nonexistent"])
        assert result == 1
        err = capsys.readouterr().err
        assert "Unknown theme" in err

    def test_theme_import_file(self, capsys, tmp_path):
        import json
        data = {
            "name": "Test Import",
            "background": "#000000", "foreground": "#FFFFFF",
            "black": "#000000", "red": "#FF0000", "green": "#00FF00",
            "yellow": "#FFFF00", "blue": "#0000FF", "purple": "#800080",
            "cyan": "#00FFFF", "white": "#C0C0C0",
            "brightBlack": "#808080", "brightRed": "#FF8080",
            "brightGreen": "#80FF80", "brightYellow": "#FFFF80",
            "brightBlue": "#8080FF", "brightPurple": "#FF80FF",
            "brightCyan": "#80FFFF", "brightWhite": "#FFFFFF",
        }
        theme_file = tmp_path / "custom.json"
        theme_file.write_text(json.dumps(data))
        with mock.patch("clippy.themes._themes_dir", return_value=tmp_path / "themes"), \
             mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            result = main(["--theme-import", str(theme_file)])
        assert result == 0
        out = capsys.readouterr().out
        assert "Test Import" in out

    def test_theme_import_bad_file(self, capsys, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json")
        result = main(["--theme-import", str(bad_file)])
        assert result == 1
        err = capsys.readouterr().err
        assert "Failed to import" in err

    def test_themes_flag(self):
        with mock.patch("clippy.theme_browser.browse_themes") as mock_browse:
            result = main(["--themes"])
        assert result == 0
        mock_browse.assert_called_once()

    def test_demo_with_theme_passes_demo_theme(self):
        with mock.patch("clippy.themes.find_theme") as mock_find, \
             mock.patch("clippy.themes.apply_theme"), \
             mock.patch("clippy.demo.demo_run") as mock_demo:
            from clippy.themes import default_theme
            mock_find.return_value = default_theme()
            main(["--theme", "Tokyo Night", "--demo", "fire"])
        # demo_run should receive a theme keyword arg
        _, kwargs = mock_demo.call_args
        assert kwargs.get("theme") is not None


class TestGenerateConfigTheme:
    def test_theme_regenerates_palette(self, tmp_path):
        """When a theme is provided, palette is always regenerated."""
        from clippy.themes import default_theme
        # Pre-create a palette
        (tmp_path / "palette.toml").write_text("old content\n")
        generate_config(["/path/to/fire.py"], config_dir=str(tmp_path), theme=default_theme())
        content = (tmp_path / "palette.toml").read_text()
        assert content != "old content\n"
        assert "foreground" in content

    def test_no_theme_preserves_existing_palette(self, tmp_path):
        """Without a theme, existing palette is not touched."""
        (tmp_path / "palette.toml").write_text("custom = [1, 2, 3]\n")
        generate_config(["/path/to/fire.py"], config_dir=str(tmp_path))
        assert (tmp_path / "palette.toml").read_text() == "custom = [1, 2, 3]\n"


class TestGenerateConfigSinglePlugin:
    def test_single_plugin_block(self, tmp_path):
        config_dir = generate_config(
            effect_paths=["/path/to/fire.py"],
            config_dir=str(tmp_path),
        )
        content = (Path(config_dir) / "tattoy.toml").read_text()
        assert content.count("[[plugins]]") == 1
        assert "layer = 1" in content


# ---------------------------------------------------------------------------
# _parse_effect_names unit tests
# ---------------------------------------------------------------------------

class TestParseEffectNames:
    def test_single_valid(self):
        valid, invalid = _parse_effect_names("fire", {"fire", "grove"})
        assert valid == ["fire"]
        assert invalid == []

    def test_comma_separated(self):
        valid, invalid = _parse_effect_names("fire,grove", {"fire", "grove"})
        assert valid == ["fire", "grove"]
        assert invalid == []

    def test_strips_whitespace(self):
        valid, invalid = _parse_effect_names(" fire , grove ", {"fire", "grove"})
        assert valid == ["fire", "grove"]
        assert invalid == []

    def test_lowercases(self):
        valid, invalid = _parse_effect_names("Fire,GROVE", {"fire", "grove"})
        assert valid == ["fire", "grove"]
        assert invalid == []

    def test_deduplicates(self):
        valid, invalid = _parse_effect_names("fire,fire,grove", {"fire", "grove"})
        assert valid == ["fire", "grove"]
        assert invalid == []

    def test_invalid_names(self):
        valid, invalid = _parse_effect_names("bogus", {"fire", "grove"})
        assert valid == []
        assert invalid == ["bogus"]

    def test_mixed_valid_invalid(self):
        valid, invalid = _parse_effect_names("fire,bogus,grove", {"fire", "grove"})
        assert valid == ["fire", "grove"]
        assert invalid == ["bogus"]

    def test_empty_string(self):
        valid, invalid = _parse_effect_names("", {"fire"})
        assert valid == []
        assert invalid == []

    def test_empty_segments(self):
        valid, invalid = _parse_effect_names("fire,,grove", {"fire", "grove"})
        assert valid == ["fire", "grove"]
        assert invalid == []
