"""Private subprocess entry point for the bounded Proposal PDF workflow."""
import sys


def main():
    import contextlib
    import os
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (50, 50))
    # Parser libraries may print diagnostics. Only extracted text reaches stdout.
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        import fitz
        from app.core.parser import extract_text_from_file
        with fitz.open(sys.argv[1]) as document:
            if document.is_encrypted or not 1 <= len(document) <= 200:
                raise ValueError("Unsupported PDF")
        result = extract_text_from_file(sys.argv[1])
        if not result.strip() or len(result) > 1_000_000:
            raise ValueError("Unsupported extracted size")
    sys.stdout.write(result)


if __name__ == "__main__":
    main()
