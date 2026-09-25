# AAOCA management LLM middleware prototype — 2026-09-26

This report contains aggregate implementation and request-preparation facts only. No patient text is copied here.

## Delivered interface

The prototype separates four independently testable stages: local request preparation, an injected provider adapter, strict response validation and non-overwriting sidecar reconciliation. No provider SDK, endpoint, model name or credential is built into the repository. Prompt text/version, routing policy and context limits are configurable.

Responses must cite request-scoped deterministic evidence IDs and/or exact passage spans. The validator rejects invented IDs, quote/span mismatches, invalid state/date combinations and unsafe disagreements. A newly proposed surgery or explicit no-surgery conclusion that lacks already verified deterministic evidence must request human review. Reconciliation preserves deterministic values until a disagreement is resolved.

## Real local preparation receipt

The default `ambiguous` policy prepared 124 requests from the validated 230-patient management package:

| Deterministic state | Requests |
|---|---:|
| `surgery` (low confidence, incomplete date, or multiple events) | 5 |
| `intended_surgery` | 11 |
| `conservative` | 20 |
| `unknown` | 88 |

The requests include all 436 available deterministic management evidence rows, with 0 evidence rows omitted by the configured limit. They contain 2,734 exact source passages and 2,778,830 passage characters. Passage characters per request range from 7,422 to 39,750, with a median of 21,820. Each request has at least one passage.

One hundred twenty-two requests explicitly report truncated broader section context, usually because the patient has more than the default maximum of 24 candidate sections. This is recorded rather than hidden; all already extracted management evidence rows were retained. The package validator checked 124 unique patients/requests and all 2,734 passage slices against source section JSON with 0 errors and 0 warnings.

The receipt records `network_processing=false`, `llm_invoked=false` and `endpoint_configured=false`. No real responses or hybrid patient labels were created.

## Verification

Synthetic tests use an injected fake client to exercise the full execution interface, valid agreement, a proposed missed surgery, exact citations and sidecar reconciliation. Separate adversarial cases confirm that a hallucinated quote and an unsafe disagreement are rejected. Custom prompt/version injection is also tested. The complete repository suite passed 77 tests; the base snapshot and deterministic management validators again passed with 0 errors and 0 warnings.

Clinical accuracy remains unmeasured. A provider/model decision, approved patient-data boundary, response set and frozen human reference are all still absent by design.
