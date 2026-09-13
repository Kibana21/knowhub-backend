"""Assert a pytest run actually executed the tests it was meant to.

A green pytest exit code proves the selected tests passed — not that anything
was selected. The integration suite in particular skips when PostgreSQL or
configuration is absent, and "8 skipped" must never read as success in CI.

Developer and CI tooling, not application code.

Usage:
    python scripts/assert_test_run.py results.xml --min-tests 8 --no-skips
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="pytest --junitxml report")
    parser.add_argument(
        "--min-tests",
        type=int,
        default=1,
        help="fail if fewer than this many tests were collected",
    )
    parser.add_argument(
        "--no-skips",
        action="store_true",
        help="fail if any test was skipped",
    )
    args = parser.parse_args(argv)

    if not args.report.is_file():
        print(f"no test report at {args.report}", file=sys.stderr)
        return 1

    root = ElementTree.parse(args.report).getroot()  # noqa: S314 - our own output
    suites = root.iter("testsuite")

    total = failures = errors = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))

    executed = total - skipped
    print(
        f"collected={total} executed={executed} skipped={skipped} "
        f"failures={failures} errors={errors}"
    )

    problems: list[str] = []
    if total < args.min_tests:
        problems.append(f"expected at least {args.min_tests} tests, collected {total}")
    if failures or errors:
        problems.append(f"{failures} failure(s), {errors} error(s)")
    if args.no_skips and skipped:
        problems.append(
            f"{skipped} test(s) skipped; this suite must actually run, not skip"
        )
    if executed < args.min_tests:
        problems.append(f"only {executed} test(s) executed")

    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
