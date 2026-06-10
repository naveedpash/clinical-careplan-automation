"""Tests for GLP-1 titration logic and FHIR bundle generation."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.engine.titration import (
    TITRATION_WEEKS,
    GLP1TitrationEngine,
    apply_adverse_event,
)
from src.models.fhir_helpers import (
    AdverseEventInput,
    PatientDemographics,
    WeightObservationInput,
)
from src.utils.terminology import (
    ADVERSE_EVENT,
    BODY_WEIGHT,
    LOINC_SYSTEM,
    NAUSEA,
    RXNORM_SYSTEM,
    SEMAGLUTIDE_025MG_PEN,
    SNOMED_SYSTEM,
)


@pytest.fixture
def patient_demographics() -> PatientDemographics:
    return PatientDemographics(
        family_name="Rivera",
        given_names=["Alex"],
        birth_date=date(1985, 3, 14),
        gender="female",
        mrn="MRN-10042",
    )


@pytest.fixture
def initial_weight() -> WeightObservationInput:
    return WeightObservationInput(value_kg=98.4, observed_on=date(2026, 6, 1))


@pytest.fixture
def start_date() -> date:
    return date(2026, 6, 2)


@pytest.fixture
def base_engine(
    patient_demographics: PatientDemographics,
    initial_weight: WeightObservationInput,
    start_date: date,
) -> GLP1TitrationEngine:
    return GLP1TitrationEngine(
        demographics=patient_demographics,
        initial_weight=initial_weight,
        start_date=start_date,
    )


class TestTitrationSchedule:
    """Verify core 4-week Semaglutide titration scheduling."""

    def test_standard_plan_has_four_weeks_at_025mg(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        plan = base_engine.compute_titration_plan()

        assert len(plan.weeks) == TITRATION_WEEKS
        assert all(week.dose_mg == 0.25 for week in plan.weeks)
        assert plan.requires_provider_triage is False
        assert plan.escalation_delayed is False

    def test_weeks_are_sequential_without_gaps(
        self,
        base_engine: GLP1TitrationEngine,
        start_date: date,
    ) -> None:
        plan = base_engine.compute_titration_plan()

        assert plan.weeks[0].start_date == start_date
        for previous, current in zip(plan.weeks[:-1], plan.weeks[1:], strict=True):
            assert current.start_date == previous.end_date + timedelta(days=1)


class TestAdverseEventHandling:
    """Verify dynamic titration changes when severe adverse events occur."""

    def test_severe_nausea_triggers_provider_triage_task(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        severe_nausea = AdverseEventInput(
            code=NAUSEA,
            severity="severe",
            observed_on=date(2026, 6, 5),
            loinc_code=ADVERSE_EVENT,
        )
        engine = apply_adverse_event(base_engine, severe_nausea)
        result = engine.generate_bundle()

        plan = result.titration_plan
        assert plan.requires_provider_triage is True
        assert plan.escalation_delayed is True
        assert len(result.task_ids) == 1

        task_resources = [
            entry["resource"]
            for entry in result.bundle["entry"]
            if entry["resource"]["resourceType"] == "Task"
        ]
        assert len(task_resources) == 1
        task = task_resources[0]
        assert task["status"] == "requested"
        assert task["owner"]["reference"] == "PractitionerRole/mock-practitioner-role-001"
        assert "Nausea" in task["description"]

    def test_mild_nausea_does_not_create_task(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        mild_nausea = AdverseEventInput(
            severity="mild",
            observed_on=date(2026, 6, 5),
        )
        engine = apply_adverse_event(base_engine, mild_nausea)
        result = engine.generate_bundle()

        assert result.titration_plan.requires_provider_triage is False
        assert result.task_ids == []

        task_count = sum(
            1
            for entry in result.bundle["entry"]
            if entry["resource"]["resourceType"] == "Task"
        )
        assert task_count == 0

    def test_severe_event_delays_subsequent_week_start(
        self,
        base_engine: GLP1TitrationEngine,
        start_date: date,
    ) -> None:
        severe_nausea = AdverseEventInput(
            severity="severe",
            observed_on=date(2026, 6, 5),
        )
        baseline = base_engine.compute_titration_plan()
        adjusted = apply_adverse_event(base_engine, severe_nausea).compute_titration_plan()

        assert baseline.weeks[1].start_date < adjusted.weeks[1].start_date
        assert adjusted.weeks[1].delayed is True

    def test_changing_side_effect_profile_dynamically_flags_task_creation(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        """Simulate a patient reporting no symptoms, then severe nausea mid-titration."""
        initial_result = base_engine.generate_bundle()
        assert initial_result.task_ids == []

        severe_event = AdverseEventInput(
            severity="severe",
            observed_on=date(2026, 6, 10),
        )
        updated_engine = apply_adverse_event(base_engine, severe_event)
        updated_result = updated_engine.generate_bundle()

        assert len(updated_result.task_ids) == 1
        assert updated_result.titration_plan.escalation_delayed is True

        adverse_observations = [
            entry["resource"]
            for entry in updated_result.bundle["entry"]
            if entry["resource"]["resourceType"] == "Observation"
            and entry["resource"]["code"]["coding"][0]["code"] == ADVERSE_EVENT.code
        ]
        assert len(adverse_observations) == 1
        assert adverse_observations[0]["valueCodeableConcept"]["coding"][0]["code"] == NAUSEA.code


class TestFHIRBundleCompliance:
    """Verify FHIR R4 resource structure and embedded terminology codes."""

    def test_bundle_is_transaction_type(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        result = base_engine.generate_bundle()
        assert result.bundle["resourceType"] == "Bundle"
        assert result.bundle["type"] == "transaction"
        assert len(result.bundle["entry"]) >= 6

    def test_patient_us_core_profile(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        result = base_engine.generate_bundle()
        patient = next(
            entry["resource"]
            for entry in result.bundle["entry"]
            if entry["resource"]["resourceType"] == "Patient"
        )
        assert "us-core-patient" in patient["meta"]["profile"][0]
        assert patient["name"][0]["family"] == "Rivera"

    def test_body_weight_uses_loinc_29463_7(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        result = base_engine.generate_bundle()
        weight_obs = next(
            entry["resource"]
            for entry in result.bundle["entry"]
            if entry["resource"]["resourceType"] == "Observation"
            and entry["resource"]["code"]["coding"][0]["code"] == BODY_WEIGHT.code
        )
        coding = weight_obs["code"]["coding"][0]
        assert coding["system"] == LOINC_SYSTEM
        assert coding["code"] == "29463-7"
        assert weight_obs["valueQuantity"]["unit"] == "kg"

    def test_medication_requests_use_rxnorm_semaglutide(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        result = base_engine.generate_bundle()
        med_requests = [
            entry["resource"]
            for entry in result.bundle["entry"]
            if entry["resource"]["resourceType"] == "MedicationRequest"
        ]
        assert len(med_requests) == TITRATION_WEEKS

        for med in med_requests:
            coding = med["medicationCodeableConcept"]["coding"][0]
            assert coding["system"] == RXNORM_SYSTEM
            assert coding["code"] == SEMAGLUTIDE_025MG_PEN.code
            assert med["status"] == "active"
            assert med["intent"] == "order"

    def test_care_plan_active_weight_management(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        result = base_engine.generate_bundle()
        care_plan = next(
            entry["resource"]
            for entry in result.bundle["entry"]
            if entry["resource"]["resourceType"] == "CarePlan"
        )
        assert care_plan["status"] == "active"
        assert care_plan["intent"] == "plan"
        assert care_plan["category"][0]["text"] == "weight-management"
        assert len(care_plan["activity"]) == TITRATION_WEEKS

    def test_no_lazy_string_interpolation_in_codings(
        self,
        base_engine: GLP1TitrationEngine,
    ) -> None:
        """Every coding must expose system, code, and display keys explicitly."""
        result = base_engine.generate_bundle()
        bundle_json = json.dumps(result.bundle)

        for system_uri in (LOINC_SYSTEM, RXNORM_SYSTEM, SNOMED_SYSTEM):
            assert system_uri in bundle_json

        for entry in result.bundle["entry"]:
            resource = entry["resource"]
            if "code" in resource and "coding" in resource["code"]:
                for coding in resource["code"]["coding"]:
                    assert "system" in coding
                    assert "code" in coding
                    assert "display" in coding


class TestSampleExport:
    """Ensure sample bundles can be written to disk."""

    def test_export_creates_valid_json_file(
        self,
        base_engine: GLP1TitrationEngine,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "bundle.json"
        result = base_engine.export_bundle(output)

        assert output.exists()
        loaded = json.loads(output.read_text())
        assert loaded["resourceType"] == "Bundle"
        assert result.patient_id is not None
