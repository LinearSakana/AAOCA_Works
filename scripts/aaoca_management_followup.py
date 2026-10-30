"""Build or validate deterministic follow-up labels for unresolved AAOCA management.

Examples:
  python -X utf8 scripts/aaoca_management_followup.py build \
      --run data/derived/v0.1_full \
      --management data/derived/aaoca_management_rules_v1 \
      --output data/derived/aaoca_management_followup_v1

  python -X utf8 scripts/aaoca_management_followup.py validate \
      --run data/derived/v0.1_full \
      --management data/derived/aaoca_management_rules_v1 \
      --output data/derived/aaoca_management_followup_v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aaoca_pipeline.management_followup import validate_followup_package, write_followup_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in [
        ("build", "Create the unresolved-management follow-up package"),
        ("validate", "Validate an existing follow-up package against its sources"),
    ]:
        subparser = subparsers.add_parser(command, help=help_text)
        subparser.add_argument("--run", type=Path, required=True, help="Completed sectioned pipeline snapshot")
        subparser.add_argument("--management", type=Path, required=True, help="Validated deterministic Management package")
        subparser.add_argument("--output", type=Path, required=True, help="Separate derived follow-up output directory")
        if command == "build":
            subparser.add_argument("--rules", type=Path, help="Optional JSON rules override")
    args = parser.parse_args()
    if args.command == "build":
        result = write_followup_package(args.run, args.management, args.output, args.rules)
        validation = result["validation"]
    else:
        validation = validate_followup_package(args.output, args.run, args.management)
        result = validation
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if validation.get("validation_status") == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
