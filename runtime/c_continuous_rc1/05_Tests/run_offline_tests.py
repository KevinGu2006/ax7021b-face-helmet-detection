"""Run the actual Fake tests and save a clean unittest PASS/FAIL log."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import unittest


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent / "01_Async_Live"))
    suite = unittest.TestSuite([
        unittest.TestLoader().discover(str(root / "tests")),
        unittest.TestLoader().discover(str(root / "serial_tests")),
    ])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    log = output.getvalue()
    (root / "rc1_fake_test.log").write_text(log, encoding="utf-8")
    print(log, end="")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
