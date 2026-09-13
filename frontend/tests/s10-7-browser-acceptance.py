#!/usr/bin/env python3
"""Sprint 10.7 final whole-platform real-Chromium acceptance (180+ cases)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('s107_acceptance_base', here / 's10-6-browser-acceptance.py')
assert spec and spec.loader
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)
suite.OUT = Path(__file__).resolve().parents[2] / 'docs/audits/s10_7/browser'
os.environ['PLASMA_S107_MODE'] = '1'

if __name__ == '__main__':
    raise SystemExit(suite.main())
