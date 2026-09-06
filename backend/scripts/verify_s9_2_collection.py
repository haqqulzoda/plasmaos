"""Collect backend tests while rejecting network, process and cwd side effects.

Run with the normal test dependencies and synthetic environment. This does not
start infrastructure or execute tests. It also imports the renamed proof modules
under the same guard to catch broken internal imports without running proofs.
"""


def main():
    import importlib
    import os
    from pathlib import Path
    import socket
    import subprocess
    import sys
    from unittest.mock import patch
    import pytest

    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    violations = []

    def forbidden(*args, **kwargs):
        violations.append("network/process/chdir during collection")
        raise AssertionError(violations[-1])

    class CollectionGuard:
        def pytest_collection(self, session):
            self.patches = [
                patch.object(socket.socket, "connect", forbidden),
                patch.object(socket.socket, "connect_ex", forbidden),
                patch.object(socket, "create_connection", forbidden),
                patch.object(subprocess, "Popen", forbidden),
                patch.object(os, "system", forbidden),
                patch.object(os, "chdir", forbidden),
            ]
            for guard in self.patches:
                guard.start()
            for path in sorted((backend / "scripts").glob("verify_*.py")):
                if path.name != Path(__file__).name:
                    importlib.import_module("scripts." + path.stem)

        def pytest_collection_finish(self, session):
            self.restore()

        def restore(self):
            for guard in reversed(getattr(self, "patches", [])):
                guard.stop()
            self.patches = []

    guard = CollectionGuard()
    try:
        status = pytest.main([str(backend), "--collect-only", "-q"], plugins=[guard])
    finally:
        guard.restore()
    if violations:
        raise SystemExit("Collection attempted operational I/O")
    print("Collection operational side effects: 0")
    raise SystemExit(status)


if __name__ == "__main__":
    main()
