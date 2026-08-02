from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from lavatune.app import UiState, _handle_action, _make_controls, _save_pending_preferences
from lavatune.config import DEFAULT_THEME, load_config, save_preferences


class ConfigTests(unittest.TestCase):
    def test_soft_afterglow_is_the_default_theme(self) -> None:
        config = load_config(None, None)

        self.assertEqual(config.theme, DEFAULT_THEME)
        self.assertFalse(config.render.show_stats)

    def test_warm_braille_theme_name_remains_compatible(self) -> None:
        self.assertEqual(load_config(None, "warm-braille").theme, DEFAULT_THEME)

    def test_builtin_themes_resolve_to_renderable_values(self) -> None:
        cool = load_config(None, "cool-dense")
        mono = load_config(None, "mono-blocks")

        self.assertEqual(cool.render.palette, "ice")
        self.assertGreater(len(set(cool.render.glyphs)), 2)
        self.assertEqual(mono.render.palette, "mono")
        self.assertIn("█", mono.render.glyphs)

    def test_preferences_round_trip_semantic_controls_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "preferences.json"
            config = load_config(None, None)
            config.render.material = "fluid"
            config.render.weight = "full"
            config.render.edge = "defined"
            config.render.afterglow = "quiet"
            config.lava.reactivity = 1.45

            save_preferences(config, path)
            restored = load_config(None, None, saved_preferences=path)

            self.assertEqual(restored.render.material, "fluid")
            self.assertEqual(restored.render.weight, "full")
            self.assertEqual(restored.render.edge, "defined")
            self.assertEqual(restored.render.afterglow, "quiet")
            self.assertEqual(restored.lava.reactivity, 1.45)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_explicit_config_overrides_saved_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferences = root / "preferences.json"
            authored = root / "authored.toml"
            config = load_config(None, None)
            config.render.material = "fluid"
            config.render.weight = "full"
            save_preferences(config, preferences)
            authored.write_text('[render]\nmaterial = "text"\nweight = "airy"\n')

            loaded = load_config(str(authored), None, saved_preferences=preferences)

            self.assertEqual(loaded.render.material, "text")
            self.assertEqual(loaded.render.weight, "airy")

    def test_unknown_preference_schema_fails_with_a_bounded_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text(json.dumps({"schema": 99}))

            with self.assertRaisesRegex(ValueError, "Unsupported preferences schema"):
                load_config(None, None, saved_preferences=path)

    def test_legacy_glyph_config_defaults_to_text_material(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.toml"
            path.write_text('[render]\nglyphs = " .xX"\npalette = "mono"\n')

            loaded = load_config(str(path), None)

            self.assertEqual(loaded.render.material, "text")
            self.assertEqual(loaded.render.glyphs, " .xX")

    def test_dock_adjustment_debounces_into_saved_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "preferences.json"
            config = load_config(None, None)
            ui = UiState(tab_index=1)
            controls = _make_controls(config)

            _handle_action("adjust:0", 1, config, ui, controls)
            self.assertTrue(ui.preferences_dirty)
            _save_pending_preferences(config, ui, destination, force=True)
            restored = load_config(None, None, saved_preferences=destination)

            self.assertFalse(ui.preferences_dirty)
            self.assertEqual(restored.render.material, "fluid")

    def test_explicit_config_mode_disables_preference_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "preferences.json"
            config = load_config(None, None)
            ui = UiState(preferences_dirty=True)

            _save_pending_preferences(config, ui, None, force=True)

            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
