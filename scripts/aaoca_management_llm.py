"""Select, prepare and run bounded AAOCA management review with local tools.

The recommended v2 commands are triage, prepare-agent, run-agent and
validate-agent. Only run-agent invokes DeepSeek, using DEEPSEEK_API_KEY.
The original offline v1 commands remain available for historical artifacts.

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
    validate_hybrid_package,
)
from aaoca_pipeline.management_agent import (
    prepare_review, run_review, triage, validate_review_package, validate_review_run,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("triage", help="Offline semantic-need routing of the current cohort")
    agent_prepare = subparsers.add_parser("prepare-agent", help="Prepare at most 3 selected v2 cases, without a model call")
    for command in [route, agent_prepare]:
        command.add_argument("--management", type=Path, required=True)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--aaoca-review", type=Path, required=True)
    agent_prepare.add_argument("--output", type=Path, required=True)
    agent_prepare.add_argument("--patient-id", action="append", help="Repeat for 1..3 eligible patients; default selects highest scores")
    agent_prepare.add_argument("--max-cases", type=int, default=3)
    agent_run = subparsers.add_parser("run-agent", help="One paid DeepSeek batch; no automatic retries")
    agent_run.add_argument("--requests", type=Path, required=True)
    agent_run.add_argument("--output", type=Path, required=True)
    agent_run.add_argument("--max-model-calls-per-case", type=int, default=2)
    agent_run.add_argument("--max-total-calls", type=int, default=6)
    agent_validate = subparsers.add_parser("validate-agent", help="Offline validation of v2 requests and optional results")
    agent_validate.add_argument("--requests", type=Path, required=True)
    agent_validate.add_argument("--output", type=Path, help="Validate a saved run as well as its request package")

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
    validate_responses.add_argument("--management", type=Path, help="Also verify current deterministic source hashes")
    validate_responses.add_argument("--run", type=Path, help="Also verify exact source passages")

    reconcile = subparsers.add_parser("reconcile", help="Create a non-overwriting deterministic/LLM sidecar")
    reconcile.add_argument("--management", type=Path, required=True)
    reconcile.add_argument("--requests", type=Path, required=True)
    reconcile.add_argument("--responses", type=Path, required=True)
    reconcile.add_argument("--output", type=Path, required=True)
    reconcile.add_argument("--run", type=Path)

    validate_hybrid = subparsers.add_parser("validate-hybrid", help="Check a sidecar against its current sources")
    validate_hybrid.add_argument("--output", type=Path, required=True)
    validate_hybrid.add_argument("--management", type=Path, required=True)
    validate_hybrid.add_argument("--requests", type=Path, required=True)
    validate_hybrid.add_argument("--responses", type=Path, required=True)
    validate_hybrid.add_argument("--run", type=Path)

    args = parser.parse_args()
    if args.command == "triage":
        from collections import Counter
        rows, _, _, _ = triage(args.management, args.run, args.aaoca_review)
        result = {"routing_counts": dict(Counter(row["route"] for row in rows)),
                  "eligible": sorted([row for row in rows if row["route"] == "needs_llm"], key=lambda row: (-row["score"], row["patient_id"]))}
    elif args.command == "prepare-agent":
        result = prepare_review(args.management, args.run, args.aaoca_review, args.output,
                                patient_ids=args.patient_id, max_cases=args.max_cases)
    elif args.command == "run-agent":
        result = run_review(args.requests, args.output, max_model_calls=args.max_model_calls_per_case,
                            max_total_calls=args.max_total_calls)
    elif args.command == "validate-agent":
        result = validate_review_run(args.requests, args.output) if args.output else validate_review_package(args.requests)
    elif args.command == "prepare":
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
            management_root=args.management,
            run_root=args.run,
        )
    elif args.command == "reconcile":
        result = reconcile_llm_responses(args.management, args.requests, args.responses, args.output, run_root=args.run)
    else:
        result = validate_hybrid_package(args.output, args.management, args.requests, args.responses, run_root=args.run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    validation_status = result.get("validation_status")
    if validation_status is None:
        validation_status = result.get("validation", result.get("response_validation", {})).get("validation_status")
    return 0 if validation_status in {None, "passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
