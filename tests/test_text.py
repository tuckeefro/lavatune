from __future__ import annotations

import unittest

from lavatune.text import sanitize_display_text


class DisplayTextTests(unittest.TestCase):
    def test_controls_and_invisible_formatting_become_spaces(self) -> None:
        value = "audio\x1b]0;spoof\x07\u202ereversed\u200b title"

        self.assertEqual(sanitize_display_text(value), "audio ]0;spoof reversed title")

    def test_limit_applies_after_normalization(self) -> None:
        self.assertEqual(sanitize_display_text("  abc  def  ", max_chars=5), "abc d")


if __name__ == "__main__":
    unittest.main()
