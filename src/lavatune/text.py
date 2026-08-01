"""Terminal-safe handling for text received from local programs."""

from __future__ import annotations

import unicodedata


def sanitize_display_text(value: str, max_chars: int = 240) -> str:
    """Collapse controls and invisible formatting before terminal display."""
    printable = (
        " " if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
        for character in value
    )
    return " ".join("".join(printable).split())[:max_chars]
