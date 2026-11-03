"""Text normalization, span location and script detection.

Matching uses a normalized view of the source text that is tolerant of layout
noise only: Unicode NFKC, case folding, whitespace runs, apostrophe variants
(important for Uzbek Latin o‘/g‘, written with ‘ ’ ʻ ʼ ` ' or ´), dash variants
and quotation-mark variants. Word order and wording are never relaxed, so a
paraphrased or invented quote does not locate.
"""

from __future__ import annotations

import re
import unicodedata

Span = tuple[int, int]

# Apostrophe-like characters, including the Uzbek modifier letters ʻ (U+02BB) and ʼ (U+02BC).
_APOSTROPHES = "'`´‘’‚‛′ʹʻʼʽˈ＇"
_DASHES = "‐‑‒–—―−"
_QUOTES = "“”„‟«»\"″"
_TRANSLATE = {ord(c): "'" for c in _APOSTROPHES}
_TRANSLATE.update({ord(c): "-" for c in _DASHES})
_TRANSLATE.update({ord(c): '"' for c in _QUOTES})
_TRANSLATE[ord(" ")] = " "
# Visually identical Cyrillic/Latin pairs seen in Uzbek sources ("Оʻzbekiston" written with a
# Cyrillic О) are deliberately NOT folded: a mixed-script quote must match the source as written.


def normalize_char(character: str) -> str:
    folded = unicodedata.normalize("NFKC", character).casefold()
    return folded.translate(_TRANSLATE)


def normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalized text and, for each normalized character, its source offset."""
    out: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(text):
        normalized = normalize_char(character)
        for piece in normalized:
            if piece.isspace():
                if out and out[-1] == " ":
                    continue
                piece = " "
            out.append(piece)
            offsets.append(index)
    # strip leading/trailing spaces
    while out and out[0] == " ":
        out.pop(0)
        offsets.pop(0)
    while out and out[-1] == " ":
        out.pop()
        offsets.pop()
    return "".join(out), offsets


def normalize(text: str) -> str:
    return normalized_with_offsets(text)[0]


class SourceIndex:
    """Locates quotes in one source text; returns every occurrence as source offsets."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.normalized, self.offsets = normalized_with_offsets(text)

    def locate_all(self, quote: str) -> list[Span]:
        needle = normalize(quote).strip(" ")
        if not needle:
            return []
        spans: list[Span] = []
        start = self.normalized.find(needle)
        while start >= 0:
            end = start + len(needle) - 1
            spans.append((self.offsets[start], self.offsets[end] + 1))
            start = self.normalized.find(needle, start + 1)
        return spans


def overlap_ratio(first: Span, second: Span) -> float:
    """Overlap as a fraction of the shorter span (same rule as bench_pursuit_models.py)."""
    shorter = min(first[1] - first[0], second[1] - second[0])
    if shorter <= 0:
        return 0.0
    return max(0, min(first[1], second[1]) - max(first[0], second[0])) / shorter


def best_overlap(first: list[Span], second: list[Span]) -> float:
    return max((overlap_ratio(a, b) for a in first for b in second), default=0.0)


_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def script_of(text: str) -> str:
    """CYRILLIC, LATIN, or NONE by majority of letters; MIXED when neither has 80%."""
    cyrillic = len(_CYRILLIC.findall(text))
    latin = len(_LATIN.findall(text))
    total = cyrillic + latin
    if total == 0:
        return "NONE"
    if cyrillic / total >= 0.8:
        return "CYRILLIC"
    if latin / total >= 0.8:
        return "LATIN"
    return "MIXED"
