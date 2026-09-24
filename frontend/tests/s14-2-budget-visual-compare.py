#!/usr/bin/env python3
"""Pair the supplied budget/logo mockup with the final Explorer browser render."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("/mnt/d/Downloads/ChatGPT Image Sep 19, 2026, 07_59_46 PM.png")
RENDER = ROOT / "docs/audits/s14_2/browser/explorer-en-1440.png"
OUTPUT = ROOT / "docs/audits/s14_2/budget-logo-comparison.png"
FOCUS = ROOT / "docs/audits/s14_2/budget-logo-first-row.png"


def main() -> None:
    source = Image.open(SOURCE).convert("RGB")
    render = Image.open(RENDER).convert("RGB")
    normalized = render.copy()
    normalized.thumbnail((source.width, 2200), Image.Resampling.LANCZOS)

    full = Image.new("RGB", (source.width * 2, max(source.height, normalized.height) + 36), "white")
    full.paste(source, (0, 36))
    full.paste(normalized, (source.width, 36))
    labels = ImageDraw.Draw(full)
    labels.text((12, 12), "SUPPLIED BUDGET/LOGO MOCKUP", fill="#182638")
    labels.text((source.width + 12, 12), "EXPLORER BROWSER RENDER (fixture data)", fill="#182638")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    full.save(OUTPUT)

    source_row = source.crop((218, 442, 1288, 570))
    render_row = render.crop((256, 789, 1408, 948))
    render_row = render_row.resize(
        (source_row.width, round(render_row.height * source_row.width / render_row.width)),
        Image.Resampling.LANCZOS,
    )
    first_row = Image.new("RGB", (source_row.width * 2, max(source_row.height, render_row.height) + 36), "white")
    first_row.paste(source_row, (0, 36))
    first_row.paste(render_row, (source_row.width, 36))
    labels = ImageDraw.Draw(first_row)
    labels.text((12, 12), "MOCKUP: FIRST RESULT", fill="#182638")
    labels.text((source_row.width + 12, 12), "RENDER: FIRST RESULT", fill="#182638")
    first_row.save(FOCUS)


if __name__ == "__main__":
    main()
