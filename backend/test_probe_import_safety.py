"""Moved developer probes must remain inert when imported by tooling."""
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase


class ProbeImportSafetyTests(TestCase):
    def test_all_developer_probes_import_without_operational_side_effects(self):
        probes = Path(__file__).resolve().parent / "scripts/probes"
        program = r'''
import builtins, contextlib, io, os, pathlib, sys, types
path = pathlib.Path(sys.argv[1])
code = compile(path.read_bytes(), str(path), "exec")
module = types.ModuleType("imported_developer_probe")
module.__file__ = str(path)
before = (os.getcwd(), list(sys.path), dict(os.environ))
def forbidden(*args, **kwargs):
    raise AssertionError("probe performed an import or operational I/O")
out, err = io.StringIO(), io.StringIO()
# No dependency import may hide a network/model/PDF/environment side effect.
builtins.__import__ = forbidden
builtins.open = forbidden
io.open = forbidden
os.chdir = forbidden
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    exec(code, module.__dict__)
assert callable(module.main)
assert before == (os.getcwd(), list(sys.path), dict(os.environ))
assert not out.getvalue() and not err.getvalue()
'''
        with tempfile.TemporaryDirectory() as directory:
            for name in ("ai_probe.py", "tender_api_probe.py", "uzbek_nlp_probe.py", "extraction_probe.py"):
                with self.subTest(probe=name):
                    result = subprocess.run(
                        [sys.executable, "-I", "-B", "-c", program, str(probes / name)],
                        cwd=directory, capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
