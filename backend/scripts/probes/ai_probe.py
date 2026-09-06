"""Explicit developer PDF/Gemini probe; importing this module performs no work."""


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="PDF to analyze; may contain sensitive text")
    parser.add_argument("--env-file", type=Path, help="Explicit optional development environment file")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    from app.core.parser import extract_text_from_bytes
    from app.core.ai import analyze_tender_text

    pdf_bytes = args.pdf.read_bytes()
    text = extract_text_from_bytes(pdf_bytes, "pdf")
    print(f"PDF bytes: {len(pdf_bytes)}; extracted characters: {len(text)}")
    print(json.dumps(analyze_tender_text(text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
