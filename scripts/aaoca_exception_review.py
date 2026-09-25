"""Build or validate an exception-only AAOCA relevance review package.

Examples:
  python -X utf8 scripts/aaoca_exception_review.py build \
      --run data/derived/v0.1_full \
      --output data/review/aaoca_exception_review_v1
  python -X utf8 scripts/aaoca_exception_review.py validate \
      --output data/review/aaoca_exception_review_v1
  python -X utf8 scripts/aaoca_exception_review.py import-workbook \
      --output data/review/aaoca_exception_review_v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aaoca_pipeline.aaoca_exceptions import (
    import_review_workbook,
    validate_review_package,
    write_exception_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Create an exception-only review package")
    build.add_argument("--run", type=Path, required=True, help="Completed pipeline snapshot")
    build.add_argument("--output", type=Path, required=True, help="Local review directory under data/")

    validate = subparsers.add_parser("validate", help="Validate reviewer-editable CSV files")
    validate.add_argument("--output", type=Path, required=True, help="Review package directory")
    validate.add_argument("--require-complete", action="store_true", help="Require every exception to have a final label")

    import_workbook = subparsers.add_parser(
        "import-workbook",
        help="Copy validated human fields from the exception workbook to exception_cases.csv",
    )
    import_workbook.add_argument("--output", type=Path, required=True, help="Review package directory")
    import_workbook.add_argument(
        "--workbook",
        type=Path,
        help="Workbook path; defaults to <output>/AAOCA_exception_review.xlsx",
    )

    args = parser.parse_args()
    if args.command == "build":
        result = write_exception_package(args.run, args.output)
    elif args.command == "validate":
        result = validate_review_package(args.output, args.require_complete)
    else:
        result = import_review_workbook(args.output, args.workbook)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("validation_status", "passed") == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
