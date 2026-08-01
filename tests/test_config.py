from __future__ import annotations

import unittest

from lavatune.config import DEFAULT_THEME, load_config


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


if __name__ == "__main__":
    unittest.main()
