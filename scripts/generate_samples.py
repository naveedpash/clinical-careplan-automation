#!/usr/bin/env python3
"""Generate example FHIR transaction bundles for documentation and QA."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.engine.titration import GLP1TitrationEngine, apply_adverse_event
from src.models.fhir_helpers import (
    AdverseEventInput,
    PatientDemographics,
    WeightObservationInput,
)
from src.utils.terminology import ADVERSE_EVENT, NAUSEA

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"


def main() -> None:
    demographics = PatientDemographics(
        family_name="Rivera",
        given_names=["Alex"],
        birth_date=date(1985, 3, 14),
        gender="female",
        mrn="MRN-10042",
    )
    weight = WeightObservationInput(value_kg=98.4, observed_on=date(2026, 6, 1))
    start = date(2026, 6, 2)

    base_engine = GLP1TitrationEngine(
        demographics=demographics,
        initial_weight=weight,
        start_date=start,
    )
    base_engine.export_bundle(SAMPLES_DIR / "standard_titration_bundle.json")

    severe_nausea = AdverseEventInput(
        code=NAUSEA,
        severity="severe",
        observed_on=date(2026, 6, 5),
        loinc_code=ADVERSE_EVENT,
    )
    adverse_engine = apply_adverse_event(base_engine, severe_nausea)
    adverse_engine.export_bundle(SAMPLES_DIR / "adverse_event_titration_bundle.json")

    print(f"Wrote sample bundles to {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
