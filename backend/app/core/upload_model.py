"""Private bounded process for the existing Proposal vision analysis call."""
import contextlib
import json
import os
import sys


def main():
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    context = json.loads(sys.stdin.buffer.read(64 * 1024 + 1))
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        from app.core.ai import analyze_tender_file
        result = analyze_tender_file(sys.argv[1], context)
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Model failed")
        encoded = json.dumps(result)
        if len(encoded.encode()) > 1024 * 1024:
            raise ValueError("Model response exceeds limit")
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
