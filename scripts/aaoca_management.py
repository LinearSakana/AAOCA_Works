"""Build or validate deterministic AAOCA management outputs.

Examples:
  python -X utf8 scripts/aaoca_management.py build \
      --run data/derived/v0.1_full \
      --aaoca-review data/review/aaoca_exception_review_v1 \
      --output data/derived/aaoca_management_rules_v1
  python -X utf8 scripts/aaoca_management.py validate \
      --run data/derived/v0.1_full \
      --aaoca-review data/review/aaoca_exception_review_v1 \
      --output data/derived/aaoca_management_rules_v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aaoca_pipeline.management import validate_management_package, write_management_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in [
        ("build", "Create the deterministic management package"),
        ("validate", "Validate an existing management package"),
    ]:
        subparser = subparsers.add_parser(command, help=help_text)
        subparser.add_argument("--run", type=Path, required=True, help="Completed pipeline snapshot")
        subparser.add_argument(
            "--aaoca-review",
            type=Path,
            required=True,
            help="AAOCA exception-review package used for cohort selection",
        )
        subparser.add_argument("--output", type=Path, required=True, help="Restricted derived output directory")
    args = parser.parse_args()
    if args.command == "build":
        result = write_management_package(args.run, args.aaoca_review, args.output)
    else:
        result = validate_management_package(args.output, args.run, args.aaoca_review)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("validation_status", result.get("validation", {}).get("validation_status")) == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
