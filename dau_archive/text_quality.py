"""Checks for broken legacy font mappings in extracted PDF text."""

from __future__ import annotations


# These characters occur repeatedly when old Vietnamese fonts have no usable
# ToUnicode map. A rare copyright/trademark symbol alone is not enough.
_BROKEN_FONT_MARKERS = frozenset("¬®§ÐØÝø¸")


def looks_garbled_vietnamese(text: str) -> bool:
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return False
    bad = sum(char in _BROKEN_FONT_MARKERS or char == "\ufffd" for char in visible)
    return bad >= 3 and bad / len(visible) >= 0.01
