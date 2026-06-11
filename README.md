# clinical-careplan-automation

Production-grade GLP-1 Titration & FHIR R4 Care Plan Engine for weight-management programs.

## Overview

This engine models a standard 4-week Semaglutide initiation pathway (0.25 mg weekly) and emits a US Core–aligned FHIR R4 transaction Bundle containing:

- **Patient** (US Core profile)
- **Observation** (body weight, LOINC 29463-7)
- **CarePlan** (active, intent `plan`, category weight-management)
- **MedicationRequest** (chained weekly orders, RxNorm 1991302)
- **Task** (provider triage when severe adverse events occur)
- **Observation** (adverse event, LOINC 69453-9 with SNOMED 422587007 Nausea)

## Project Layout

```
src/
  engine/titration.py      # Core titration logic and bundle orchestration
  models/fhir_helpers.py   # FHIR R4 resource builders
  utils/terminology.py     # LOINC, RxNorm, SNOMED constants
tests/test_titration.py    # Pytest suite
data/samples/              # Example transaction bundles
```

## Quick Start

```bash
pip install -e ".[dev]"
pytest tests/ -v
python3 scripts/generate_samples.py
```

## Usage

```python
from datetime import date
from src.engine.titration import GLP1TitrationEngine, apply_adverse_event
from src.models.fhir_helpers import (
    AdverseEventInput,
    PatientDemographics,
    WeightObservationInput,
)

engine = GLP1TitrationEngine(
    demographics=PatientDemographics(
        family_name="Rivera",
        given_names=["Alex"],
        birth_date=date(1985, 3, 14),
        gender="female",
        mrn="MRN-10042",
    ),
    initial_weight=WeightObservationInput(value_kg=98.4, observed_on=date(2026, 6, 1)),
    start_date=date(2026, 6, 2),
)

result = engine.generate_bundle()

# Dynamic adverse-event handling
engine_with_ae = apply_adverse_event(
    engine,
    AdverseEventInput(severity="severe", observed_on=date(2026, 6, 5)),
)
adverse_result = engine_with_ae.generate_bundle()
assert len(adverse_result.task_ids) == 1
```

## Clinical Behavior

| Scenario | Engine Response |
|----------|-----------------|
| Standard 4-week titration | Four 0.25 mg weekly MedicationRequests |
| Severe nausea (LOINC 69453-9) | Delays subsequent week start dates, creates provider Task |
| Mild/moderate symptoms | No Task; titration schedule unchanged |

## Sample Bundles

- `data/samples/standard_titration_bundle.json` — baseline pathway
- `data/samples/adverse_event_titration_bundle.json` — severe nausea with Task
