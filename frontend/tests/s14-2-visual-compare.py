#!/usr/bin/env python3
"""Mechanical side-by-side of the supplied S14.2 mockup and browser evidence."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("/mnt/d/Downloads/redesign/explorer/ChatGPT Image Sep 16, 2026, 08_23_58 PM.png")
RENDER = ROOT / "docs/audits/s14_2/browser/explorer-en-1440.png"
OUTPUT = ROOT / "docs/audits/s14_2/design-comparison.png"
FOCUS = ROOT / "docs/audits/s14_2/design-comparison-first-row.png"


def main() -> None:
    source = Image.open(SOURCE).convert("RGB")
    rendered = Image.open(RENDER).convert("RGB")
    rendered.thumbnail((source.width, 2000), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (source.width * 2, max(source.height, rendered.height) + 36), "white")
    canvas.paste(source, (0, 36))
    canvas.paste(rendered, (source.width, 36))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), "APPROVED MOCKUP", fill="#182638")
    draw.text((source.width + 12, 12), "S14.2 BROWSER RENDER (fixture data)", fill="#182638")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT)
    source_row = source.crop((188, 476, 1099, 623))
    rendered_row = Image.open(RENDER).convert("RGB").crop((256, 789, 1408, 947))
    rendered_row = rendered_row.resize((source_row.width, round(rendered_row.height * source_row.width / rendered_row.width)), Image.Resampling.LANCZOS)
    focus = Image.new("RGB", (source_row.width * 2, max(source_row.height, rendered_row.height) + 36), "white")
    focus.paste(source_row, (0, 36))
    focus.paste(rendered_row, (source_row.width, 36))
    focused_draw = ImageDraw.Draw(focus)
    focused_draw.text((12, 12), "MOCKUP: FIRST RESULT", fill="#182638")
    focused_draw.text((source_row.width + 12, 12), "RENDER: FIRST RESULT", fill="#182638")
    focus.save(FOCUS)


if __name__ == "__main__":
    main()
