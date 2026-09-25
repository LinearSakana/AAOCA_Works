"""Prepare and validate provider-neutral AAOCA management LLM artifacts.

This CLI never calls a model. A separately approved provider adapter should
implement ``StructuredManagementLLMClient`` and call ``execute_llm_requests``
from ``aaoca_pipeline.management_llm``.

Examples:
  python -X utf8 scripts/aaoca_management_llm.py prepare \
      --management data/derived/aaoca_management_rules_v1 \
      --run data/derived/v0.1_full \
      --aaoca-review data/review/aaoca_exception_review_v1 \
      --output data/derived/aaoca_management_llm_requests_v1
  python -X utf8 scripts/aaoca_management_llm.py validate-responses \
      --requests data/derived/aaoca_management_llm_requests_v1 \
      --responses data/derived/aaoca_management_llm_responses_v1/responses.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aaoca_pipeline.management_llm import (
    PROMPT_VERSION,
    prepare_llm_request_package,
    reconcile_llm_responses,
    validate_llm_request_package,
    validate_llm_responses,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create local JSONL requests without invoking a model")
    prepare.add_argument("--management", type=Path, required=True, help="Validated deterministic management package")
    prepare.add_argument("--run", type=Path, required=True, help="Completed pipeline snapshot")
    prepare.add_argument("--aaoca-review", type=Path, required=True, help="AAOCA exception-review package")
    prepare.add_argument("--output", type=Path, required=True, help="Restricted local request package")
    prepare.add_argument(
        "--selection-policy",
        choices=["ambiguous", "review_required", "unknown", "all"],
        default="ambiguous",
        help="Which deterministic patients receive requests",
    )
    prepare.add_argument("--max-sections-per-patient", type=int, default=24)
    prepare.add_argument("--max-evidence-rows-per-patient", type=int, default=120)
    prepare.add_argument("--max-characters-per-section", type=int, default=8000)
    prepare.add_argument("--max-passage-characters-per-patient", type=int, default=80000)
    prepare.add_argument(
        "--instructions-file",
        type=Path,
        help="Optional UTF-8 prompt file; defaults to the versioned built-in instructions",
    )
    prepare.add_argument("--prompt-version", default=PROMPT_VERSION)

    validate_requests = subparsers.add_parser("validate-requests", help="Validate a prepared request package")
    validate_requests.add_argument("--requests", type=Path, required=True)
    validate_requests.add_argument("--management", type=Path)
    validate_requests.add_argument("--run", type=Path)

    validate_responses = subparsers.add_parser("validate-responses", help="Validate provider responses against requests")
    validate_responses.add_argument("--requests", type=Path, required=True)
    validate_responses.add_argument("--responses", type=Path, required=True)
    validate_responses.add_argument("--require-complete", action="store_true")

    reconcile = subparsers.add_parser("reconcile", help="Create a non-overwriting deterministic/LLM sidecar")
    reconcile.add_argument("--management", type=Path, required=True)
    reconcile.add_argument("--requests", type=Path, required=True)
    reconcile.add_argument("--responses", type=Path, required=True)
    reconcile.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        instructions = (
            args.instructions_file.read_text(encoding="utf-8")
            if args.instructions_file
            else None
        )
        prepare_kwargs = {
            "selection_policy": args.selection_policy,
            "max_sections_per_patient": args.max_sections_per_patient,
            "max_evidence_rows_per_patient": args.max_evidence_rows_per_patient,
            "max_characters_per_section": args.max_characters_per_section,
            "max_passage_characters_per_patient": args.max_passage_characters_per_patient,
            "prompt_version": args.prompt_version,
        }
        if instructions is not None:
            prepare_kwargs["instructions"] = instructions
        result = prepare_llm_request_package(
            args.management,
            args.run,
            args.aaoca_review,
            args.output,
            **prepare_kwargs,
        )
    elif args.command == "validate-requests":
        result = validate_llm_request_package(args.requests, args.management, args.run)
    elif args.command == "validate-responses":
        result = validate_llm_responses(
            args.requests,
            args.responses,
            require_complete=args.require_complete,
        )
    else:
        result = reconcile_llm_responses(args.management, args.requests, args.responses, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    validation_status = result.get("validation_status")
    if validation_status is None:
        validation_status = result.get("validation", result.get("response_validation", {})).get("validation_status")
    return 0 if validation_status in {None, "passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
