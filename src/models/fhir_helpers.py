"""FHIR R4 resource builders aligned with US Core profiles.

These helpers construct valid FHIR JSON dicts using explicit terminology
structures (system/code/display) rather than string interpolation. Each
builder returns a plain dict suitable for inclusion in a Transaction Bundle
entry, keeping the engine decoupled from a specific FHIR server SDK.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.utils.terminology import (
    ADVERSE_EVENT,
    BODY_WEIGHT,
    Coding,
    NAUSEA,
    PROVIDER_TRIAGE_TASK,
    SEMAGLUTIDE_025MG_PEN,
    WEIGHT_MANAGEMENT_CATEGORY,
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _codeable_concept(coding: Coding) -> dict[str, Any]:
    return {"coding": [coding.to_fhir()]}


def _reference(resource_type: str, resource_id: str, display: str | None = None) -> dict[str, str]:
    ref: dict[str, str] = {"reference": f"{resource_type}/{resource_id}"}
    if display:
        ref["display"] = display
    return ref


class PatientDemographics(BaseModel):
    """Minimum US Core Patient demographic fields for care-plan authoring."""

    family_name: str
    given_names: list[str]
    birth_date: date
    gender: Literal["male", "female", "other", "unknown"] = "unknown"
    mrn: str | None = None


class AdverseEventInput(BaseModel):
    """Structured adverse-event signal received from a clinical observation."""

    code: Coding = Field(default=NAUSEA)
    severity: str = Field(description="Clinical severity label, e.g. 'mild', 'moderate', 'severe'")
    observed_on: date
    loinc_code: Coding = Field(default=ADVERSE_EVENT)


class WeightObservationInput(BaseModel):
    """Initial body-weight observation used to anchor the care plan."""

    value_kg: float
    observed_on: date


def build_us_core_patient(
    demographics: PatientDemographics,
    patient_id: str | None = None,
) -> dict[str, Any]:
    """Build a US Core–aligned Patient resource.

    US Core requires name, gender, and birthDate at minimum. Identifier is
    included when an MRN is supplied to support enterprise MPI matching.
    """
    pid = patient_id or _new_id()
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": pid,
        "meta": {
            "profile": [
                "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient",
            ],
        },
        "name": [
            {
                "use": "official",
                "family": demographics.family_name,
                "given": demographics.given_names,
            },
        ],
        "gender": demographics.gender,
        "birthDate": demographics.birth_date.isoformat(),
    }
    if demographics.mrn:
        resource["identifier"] = [
            {
                "use": "usual",
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "MR",
                            "display": "Medical Record Number",
                        },
                    ],
                },
                "system": "urn:oid:2.16.840.1.113883.19.5",
                "value": demographics.mrn,
            },
        ]
    return resource


def build_body_weight_observation(
    patient_id: str,
    weight: WeightObservationInput,
    observation_id: str | None = None,
) -> dict[str, Any]:
    """Build a LOINC 29463-7 body-weight Observation tied to the patient."""
    oid = observation_id or _new_id()
    return {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs",
                    },
                ],
            },
        ],
        "code": _codeable_concept(BODY_WEIGHT),
        "subject": _reference("Patient", patient_id),
        "effectiveDateTime": f"{weight.observed_on.isoformat()}T08:00:00Z",
        "valueQuantity": {
            "value": weight.value_kg,
            "unit": "kg",
            "system": "http://unitsofmeasure.org",
            "code": "kg",
        },
    }


def build_adverse_event_observation(
    patient_id: str,
    event: AdverseEventInput,
    observation_id: str | None = None,
) -> dict[str, Any]:
    """Build a LOINC 69453-9 adverse-event Observation with SNOMED finding."""
    oid = observation_id or _new_id()
    return {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "survey",
                        "display": "Survey",
                    },
                ],
            },
        ],
        "code": _codeable_concept(event.loinc_code),
        "subject": _reference("Patient", patient_id),
        "effectiveDateTime": f"{event.observed_on.isoformat()}T12:00:00Z",
        "valueCodeableConcept": _codeable_concept(event.code),
        "interpretation": [
            {
                "text": event.severity,
            },
        ],
    }


def build_care_plan(
    patient_id: str,
    start_date: date,
    medication_request_ids: list[str],
    care_plan_id: str | None = None,
) -> dict[str, Any]:
    """Build an active weight-management CarePlan referencing titration orders.

    Intent is ``plan`` (longitudinal care pathway) rather than ``order`` because
    the engine models a multi-week titration schedule, not a single prescription
    event. Activities chain MedicationRequest fullUrls for bundle resolution.
    """
    cpid = care_plan_id or _new_id()
    activities = [
        {
            "reference": {
                "reference": f"MedicationRequest/{mrid}",
                "display": f"Semaglutide titration week {index + 1}",
            },
        }
        for index, mrid in enumerate(medication_request_ids)
    ]
    return {
        "resourceType": "CarePlan",
        "id": cpid,
        "meta": {
            "profile": [
                "http://hl7.org/fhir/us/core/StructureDefinition/us-core-careplan",
            ],
        },
        "status": "active",
        "intent": "plan",
        "category": [
            {
                "coding": [WEIGHT_MANAGEMENT_CATEGORY.to_fhir()],
                "text": "weight-management",
            },
        ],
        "subject": _reference("Patient", patient_id),
        "period": {
            "start": start_date.isoformat(),
        },
        "activity": activities,
    }


def build_medication_request(
    patient_id: str,
    week_number: int,
    dose_start: date,
    dose_end: date,
    medication: Coding = SEMAGLUTIDE_025MG_PEN,
    request_id: str | None = None,
    delayed: bool = False,
) -> dict[str, Any]:
    """Build a US Core MedicationRequest for one titration week.

    Dosage instructions follow the standard once-weekly subcutaneous Semaglutide
    initiation schedule (0.25 mg). When ``delayed`` is True, a note documents
    that escalation was held due to adverse-event triage.
    """
    rid = request_id or _new_id()
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": rid,
        "meta": {
            "profile": [
                "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest",
            ],
        },
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": _codeable_concept(medication),
        "subject": _reference("Patient", patient_id),
        "authoredOn": datetime.combine(dose_start, datetime.min.time()).isoformat() + "Z",
        "dosageInstruction": [
            {
                "sequence": 1,
                "text": (
                    f"Inject 0.25 mg subcutaneously once weekly — titration week {week_number}"
                ),
                "timing": {
                    "repeat": {
                        "frequency": 1,
                        "period": 1,
                        "periodUnit": "wk",
                        "boundsPeriod": {
                            "start": dose_start.isoformat(),
                            "end": dose_end.isoformat(),
                        },
                    },
                },
                "doseAndRate": [
                    {
                        "type": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/dose-rate-type",
                                    "code": "ordered",
                                    "display": "Ordered",
                                },
                            ],
                        },
                        "doseQuantity": {
                            "value": 0.25,
                            "unit": "mg",
                            "system": "http://unitsofmeasure.org",
                            "code": "mg",
                        },
                    },
                ],
            },
        ],
    }
    if delayed:
        resource["note"] = [
            {
                "text": (
                    "Dose escalation delayed due to severe adverse event; "
                    "maintaining 0.25 mg until provider clearance."
                ),
            },
        ]
    return resource


def build_provider_triage_task(
    patient_id: str,
    adverse_event: AdverseEventInput,
    practitioner_role_id: str = "mock-practitioner-role-001",
    task_id: str | None = None,
) -> dict[str, Any]:
    """Build a FHIR Task assigned to a practitioner role for adverse-event triage.

    Clinically, severe GLP-1 GI adverse events warrant prescriber review before
    advancing the titration ladder. The Task encodes that workflow handoff.
    """
    tid = task_id or _new_id()
    return {
        "resourceType": "Task",
        "id": tid,
        "status": "requested",
        "intent": "order",
        "priority": "urgent",
        "code": _codeable_concept(PROVIDER_TRIAGE_TASK),
        "description": (
            f"Provider triage required: {adverse_event.severity} "
            f"{adverse_event.code.display} reported on "
            f"{adverse_event.observed_on.isoformat()}. "
            "Review titration schedule and consider dose-hold."
        ),
        "for": _reference("Patient", patient_id),
        "owner": _reference("PractitionerRole", practitioner_role_id, "Weight Management Clinician"),
        "authoredOn": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reasonCode": _codeable_concept(adverse_event.code),
    }


def build_transaction_bundle(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble resources into a FHIR R4 transaction Bundle."""
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "entry": [
            {
                "fullUrl": f"urn:uuid:{entry['id']}",
                "resource": entry,
                "request": {
                    "method": "POST",
                    "url": entry["resourceType"],
                },
            }
            for entry in entries
        ],
    }
