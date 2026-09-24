#!/usr/bin/env python3
"""Place the approved S14.3 mockup beside the real browser render for QA."""

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("/mnt/d/Downloads/redesign/tenderdetails/ChatGPT Image Sep 17, 2026, 04_29_45 AM.png")
RENDER = ROOT / "docs/audits/s14_3/browser/tender-details-en-1440.png"
OUTPUT = ROOT / "docs/audits/s14_3/design-comparison.png"


def main():
    source = Image.open(SOURCE).convert("RGB")
    render = Image.open(RENDER).convert("RGB")
    render = render.resize((source.width, round(render.height * source.width / render.width)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (source.width * 2, max(source.height, render.height) + 36), "white")
    canvas.paste(source, (0, 36))
    canvas.paste(render, (source.width, 36))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), "APPROVED MOCKUP (illustrative data)", fill="#182638")
    draw.text((source.width + 12, 12), "S14.3 REAL CHROMIUM RENDER (fixture data)", fill="#182638")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT)


if __name__ == "__main__":
    main()
