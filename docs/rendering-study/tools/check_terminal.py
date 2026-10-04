"""Run every upstream test outside test_window and retain the exclusion list."""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from verify_public_sources import verify_source

ROOT = Path(__file__).resolve().parents[1]


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "_sources/lavatune-public")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence")
    options = parser.parse_args()
    source_receipt = verify_source(options.source, ROOT / "evidence/public-source-manifest.json")
    source = options.source.resolve()
    sys.path.insert(0, str(source / "src"))
    os.environ["PYTHONPATH"] = str(source / "src")
    os.environ["XDG_CONFIG_HOME"] = str(ROOT / ".private/config")
    os.environ["TERM"] = "xterm-256color"
    os.environ["LC_ALL"] = "C.UTF-8"
    os.chdir(source)
    discovered = list(flatten(unittest.defaultTestLoader.discover(str(source / "tests"))))
    excluded = [test.id() for test in discovered if test.id().startswith("test_window.")]
    included = [test for test in discovered if test.id() not in excluded]
    log = io.StringIO()
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.TestSuite(included))
    options.output.mkdir(parents=True, exist_ok=True)
    (options.output / "terminal-tests.log").write_text(log.getvalue())
    receipt = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "source_verification": source_receipt, "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "seconds": round(time.perf_counter() - started, 3), "excluded_tests": excluded,
        "exclusion_reason": "All of test_window is excluded from this terminal/core subset; the original full-suite result is retained separately.",
        "scope": "Upstream tests with mocks and synthetic inputs; no live audio or GUI validation",
        "environment": {key: os.environ[key] for key in ("PYTHONPATH", "TERM", "LC_ALL")},
    }
    (options.output / "terminal-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
