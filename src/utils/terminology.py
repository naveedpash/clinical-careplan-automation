"""FHIR terminology constants for GLP-1 titration care plans.

Centralizing coded values (LOINC, RxNorm, SNOMED CT) ensures consistent
interoperability with US Core profiles and prevents ad-hoc string literals
that break validation against HL7 terminology bindings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Coding:
    """A single terminology coding triple used in FHIR CodeableConcept structures."""

    system: str
    code: str
    display: str

    def to_fhir(self) -> dict[str, str]:
        return {
            "system": self.system,
            "code": self.code,
            "display": self.display,
        }


# ---------------------------------------------------------------------------
# Code system URIs (canonical HL7 and NLM identifiers)
# ---------------------------------------------------------------------------

LOINC_SYSTEM: Final[str] = "http://loinc.org"
RXNORM_SYSTEM: Final[str] = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED_SYSTEM: Final[str] = "http://snomed.info/sct"
ICD10_SYSTEM: Final[str] = "http://hl7.org/fhir/sid/icd-10-cm"

# ---------------------------------------------------------------------------
# Observation codes
# ---------------------------------------------------------------------------

BODY_WEIGHT: Final[Coding] = Coding(
    system=LOINC_SYSTEM,
    code="29463-7",
    display="Body weight",
)

ADVERSE_EVENT: Final[Coding] = Coding(
    system=LOINC_SYSTEM,
    code="69453-9",
    display="Adverse event",
)

# ---------------------------------------------------------------------------
# Medication codes — Semaglutide pen injector strengths
# ---------------------------------------------------------------------------

SEMAGLUTIDE_025MG_PEN: Final[Coding] = Coding(
    system=RXNORM_SYSTEM,
    code="1991302",
    display="semaglutide 0.25 MG/0.37 ML Pen Injector",
)

# ---------------------------------------------------------------------------
# Clinical finding codes
# ---------------------------------------------------------------------------

NAUSEA: Final[Coding] = Coding(
    system=SNOMED_SYSTEM,
    code="422587007",
    display="Nausea",
)

# ---------------------------------------------------------------------------
# Care plan and task category codes
# ---------------------------------------------------------------------------

WEIGHT_MANAGEMENT_CATEGORY: Final[Coding] = Coding(
    system=SNOMED_SYSTEM,
    code="718347000",
    display="Weight management program",
)

PROVIDER_TRIAGE_TASK: Final[Coding] = Coding(
    system=SNOMED_SYSTEM,
    code="185389009",
    display="Follow-up visit",
)

# ---------------------------------------------------------------------------
# Severity interpretation for adverse events
# ---------------------------------------------------------------------------

SEVERE_SEVERITY_TEXT: Final[str] = "severe"
