"""Future enrichment contract; v0.1 does not load or invoke any LLM.

Implementations must be separately authorized and run locally. Candidates are
separate from source sections: an inference must never overwrite evidence,
identity, document dates, or the text-layer/OCR provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EvidenceReference:
    document_id: str
    section_id: str
    page: int
    text_path: str
    text_reference: str
    evidence_text: str


@dataclass(frozen=True)
class EnrichmentCandidate:
    field: str
    value: str
    evidence: EvidenceReference
    method: str
    method_version: str
    confidence: float | None
    # Recommendation/planning/completion must not become the same assertion.
    assertion_status: str = "unknown"
    reviewed: bool = False


class LocalEnrichmentAdapter(Protocol):
    def extract(self, section: dict) -> list[EnrichmentCandidate]:
        """Produce reviewable candidates from a provenance-bearing section."""
        ...
