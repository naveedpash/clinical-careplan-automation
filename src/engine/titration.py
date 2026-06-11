"""GLP-1 titration and care-plan engine.

Models a standard 4-week Semaglutide initiation pathway (0.25 mg weekly) and
dynamically adjusts the schedule when adverse-event observations are received.
The engine emits a single FHIR R4 transaction Bundle suitable for US Core
validation pipelines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.models.fhir_helpers import (
    AdverseEventInput,
    PatientDemographics,
    WeightObservationInput,
    build_adverse_event_observation,
    build_body_weight_observation,
    build_care_plan,
    build_medication_request,
    build_provider_triage_task,
    build_transaction_bundle,
    build_us_core_patient,
)
from src.utils.terminology import SEVERE_SEVERITY_TEXT, SEMAGLUTIDE_025MG_PEN


TITRATION_WEEKS: int = 4
STANDARD_DOSE_MG: float = 0.25
ESCALATION_DELAY_DAYS: int = 7


@dataclass
class TitrationWeek:
    """One week in the Semaglutide titration ladder."""

    week_number: int
    dose_mg: float
    start_date: date
    end_date: date
    delayed: bool = False


@dataclass
class TitrationPlan:
    """Computed titration schedule plus metadata for bundle generation."""

    weeks: list[TitrationWeek]
    adverse_events: list[AdverseEventInput] = field(default_factory=list)
    requires_provider_triage: bool = False
    escalation_delayed: bool = False


@dataclass
class CarePlanEngineResult:
    """Output of the care-plan engine: plan metadata and FHIR bundle."""

    titration_plan: TitrationPlan
    bundle: dict[str, Any]
    patient_id: str
    care_plan_id: str
    task_ids: list[str]


class GLP1TitrationEngine:
    """Production-grade GLP-1 titration and FHIR care-plan generator.

    Clinical rationale
    ------------------
    GLP-1 receptor agonists require gradual dose escalation to improve GI
    tolerability. A 4-week 0.25 mg Semaglutide initiation mirrors common
    real-world protocols before advancing to higher maintenance doses. When a
    patient reports a *severe* adverse event (e.g., nausea via LOINC 69453-9),
    clinical guidelines recommend holding escalation and engaging the
    prescriber — modeled here as a date shift on subsequent weeks and a FHIR
    Task for provider triage.
    """

    def __init__(
        self,
        demographics: PatientDemographics,
        initial_weight: WeightObservationInput,
        start_date: date,
        adverse_events: list[AdverseEventInput] | None = None,
    ) -> None:
        self.demographics = demographics
        self.initial_weight = initial_weight
        self.start_date = start_date
        self.adverse_events = adverse_events or []

    def compute_titration_plan(self) -> TitrationPlan:
        """Derive the 4-week titration schedule, applying adverse-event holds."""
        severe_events = [
            event
            for event in self.adverse_events
            if event.severity.lower() == SEVERE_SEVERITY_TEXT
        ]
        delay_days = len(severe_events) * ESCALATION_DELAY_DAYS

        weeks: list[TitrationWeek] = []
        cursor = self.start_date

        for week_index in range(TITRATION_WEEKS):
            week_number = week_index + 1
            week_start = cursor
            if week_index > 0 and delay_days > 0:
                week_start = cursor + timedelta(days=delay_days)
            week_end = week_start + timedelta(days=6)

            event_in_week = any(
                event.observed_on <= week_end and event.observed_on >= week_start
                for event in severe_events
            )

            weeks.append(
                TitrationWeek(
                    week_number=week_number,
                    dose_mg=STANDARD_DOSE_MG,
                    start_date=week_start,
                    end_date=week_end,
                    delayed=event_in_week or (week_index > 0 and delay_days > 0),
                ),
            )
            cursor = week_end + timedelta(days=1)

        return TitrationPlan(
            weeks=weeks,
            adverse_events=self.adverse_events,
            requires_provider_triage=len(severe_events) > 0,
            escalation_delayed=delay_days > 0,
        )

    def generate_bundle(
        self,
        patient_id: str | None = None,
        care_plan_id: str | None = None,
    ) -> CarePlanEngineResult:
        """Generate a complete FHIR transaction Bundle for the titration pathway."""
        plan = self.compute_titration_plan()

        patient = build_us_core_patient(self.demographics, patient_id)
        pid = patient["id"]

        weight_obs = build_body_weight_observation(pid, self.initial_weight)

        medication_requests: list[dict[str, Any]] = []
        med_ids: list[str] = []

        for week in plan.weeks:
            med = build_medication_request(
                patient_id=pid,
                week_number=week.week_number,
                dose_start=week.start_date,
                dose_end=week.end_date,
                medication=SEMAGLUTIDE_025MG_PEN,
                delayed=week.delayed,
            )
            medication_requests.append(med)
            med_ids.append(med["id"])

        cpid = care_plan_id or f"careplan-{pid[:8]}"
        care_plan = build_care_plan(pid, self.start_date, med_ids, cpid)

        resources: list[dict[str, Any]] = [
            patient,
            weight_obs,
            care_plan,
            *medication_requests,
        ]

        task_ids: list[str] = []
        if plan.requires_provider_triage:
            for severe in (
                event
                for event in plan.adverse_events
                if event.severity.lower() == SEVERE_SEVERITY_TEXT
            ):
                task = build_provider_triage_task(pid, severe)
                resources.append(task)
                task_ids.append(task["id"])
                ae_obs = build_adverse_event_observation(pid, severe)
                resources.append(ae_obs)

        bundle = build_transaction_bundle(resources)

        return CarePlanEngineResult(
            titration_plan=plan,
            bundle=bundle,
            patient_id=pid,
            care_plan_id=cpid,
            task_ids=task_ids,
        )

    def export_bundle(self, output_path: Path) -> CarePlanEngineResult:
        """Generate the bundle and persist it as formatted JSON."""
        result = self.generate_bundle()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.bundle, indent=2),
            encoding="utf-8",
        )
        return result


def apply_adverse_event(
    engine: GLP1TitrationEngine,
    event: AdverseEventInput,
) -> GLP1TitrationEngine:
    """Return a new engine instance with an additional adverse-event observation.

    This functional update pattern keeps titration state immutable and makes it
    straightforward to replay event streams in audit or simulation pipelines.
    """
    updated_events = [*engine.adverse_events, event]
    return GLP1TitrationEngine(
        demographics=engine.demographics,
        initial_weight=engine.initial_weight,
        start_date=engine.start_date,
        adverse_events=updated_events,
    )
