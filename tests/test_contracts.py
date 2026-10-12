import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from smartfill.__main__ import export_schemas, validate_example
from smartfill.contracts import (
    CellLocator, DateValue, Document, FillingResult, GroundTruth, IntegerValue, PageLocator,
    TaskInput, TextLocator,
)
from smartfill.integrity import validate_ground_truth, verify_artifacts

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "data" / "examples"


def read(name="normal", filename="result.json"):
    return json.loads((EXAMPLES / name / filename).read_text(encoding="utf-8"))


def parse(data, model=FillingResult):
    return model.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("name,status,requests", [("normal", "completed", 0), ("conflict", "needs_review", 1)])
def test_examples_are_auditable_and_round_trip(name, status, requests):
    result = parse(read(name))
    assert FillingResult.model_validate_json(result.model_dump_json()) == result
    assert result.task_status == status
    assert result.fields[-1].suggested_value.value == 5
    assert result.fields[-1].derivation.input_fact_ids == ["f-departure-invitation", "f-return-invitation"]
    summary = validate_example(EXAMPLES / name)
    assert summary["pending_requests"] == requests
    assert summary["artifact_integrity"] == "passed"
    passport = next(f for f in result.fields if f.field_id == "passport")
    if name == "conflict":
        assert passport.suggested_value is None
        assert len(passport.candidate_ids) == len(passport.evidence_ids) == 2
        assert {c.value.value for c in result.candidates if c.field_id == "passport"} == {"P00001234", "P00005678"}


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(task_id="different-task"),
    lambda d: d["evidence"][0].update(quote="fictional source"),
    lambda d: d["evidence"][0].update(end=99999),
    lambda d: d["evidence"][0].update(segment_id="missing-segment"),
    lambda d: d["evidence"][0]["locator"].update(line_start=99, line_end=99),
    lambda d: d["evidence"].append(copy.deepcopy(d["evidence"][0])),
    lambda d: d["facts"].append(copy.deepcopy(d["facts"][0])),
    lambda d: d["fields"].append(copy.deepcopy(d["fields"][0])),
    lambda d: d["facts"][0].update(evidence_ids=["missing-evidence"]),
    lambda d: d["facts"][0].update(raw_value="unsupported raw fact"),
    lambda d: d["candidates"][0].update(field_id="missing-field"),
    lambda d: d["candidates"][0].update(evidence_ids=["e-passport-passport"]),
    lambda d: d["candidates"][0]["value"].update(value="unsupported new value"),
    lambda d: d["fields"][0].update(selected_candidate_id="c-passport-passport"),
    lambda d: d["fields"][0].update(evidence_ids=[]),
    lambda d: d["fields"][0].update(candidate_ids=["c-name-passport", "c-passport-passport"]),
    lambda d: d["fields"][0]["suggested_value"].update(value="different person"),
    lambda d: d["fields"][-1]["derivation"].update(rule_id="undeclared-rule"),
    lambda d: d["fields"][-1]["derivation"].update(rule_version="wrong-version"),
    lambda d: d["fields"][-1]["derivation"].update(input_fact_ids=["f-return-invitation", "f-departure-invitation"]),
    lambda d: d["fields"][-1]["derivation"]["output"].update(value=6),
    lambda d: d["fields"][-1].update(derivation=None),
    lambda d: d.update(task_status="needs_review"),
    lambda d: d.update(task_status="failed"),
    lambda d: d["fields"].pop(),
    lambda d: d["form_schema"]["fields"][0]["target_locator"].update(line_start=99, line_end=99),
    lambda d: d["task_input"].update(ground_truth={}),
], ids=[
    "task-identity", "fake-quote", "out-of-bounds-span", "missing-segment", "wrong-location",
    "duplicate-evidence", "duplicate-fact", "duplicate-field", "orphan-fact", "unsupported-fact",
    "unknown-field", "unrelated-evidence", "hallucinated-candidate", "wrong-selection", "no-evidence",
    "foreign-candidate", "wrong-final-value", "unknown-calculation-rule", "wrong-rule-version",
    "reversed-date-inputs", "wrong-calculation", "no-calculation-chain", "wrong-task-status",
    "failure-without-error", "unreported-field", "invalid-target-location", "gold-leakage",
])
def test_rejects_invalid_result(mutation):
    data = read()
    mutation(data)
    with pytest.raises(ValidationError):
        parse(data)


def test_conflict_cannot_be_filled_or_silently_resolved():
    data = read("conflict")
    passport = next(f for f in data["fields"] if f["field_id"] == "passport")
    passport["suggested_value"] = {"kind": "text", "value": "P00001234"}
    with pytest.raises(ValidationError):
        parse(data)
    passport.update(status="verified", selected_candidate_id="c-passport-passport", issue_ids=[])
    data.update(issues=[], review_requests=[], task_status="completed")
    with pytest.raises(ValidationError, match="differing candidates"):
        parse(data)


def test_conflict_requires_matching_confirmation_request():
    data = read("conflict")
    data["review_requests"] = []
    with pytest.raises(ValidationError, match="matching next action"):
        parse(data)


def missing_result():
    data = read()
    data["candidates"] = [c for c in data["candidates"] if c["field_id"] != "passport"]
    passport = next(f for f in data["fields"] if f["field_id"] == "passport")
    passport.update(status="missing", suggested_value=None, selected_candidate_id=None,
                    candidate_ids=[], evidence_ids=[], issue_ids=["missing-passport"])
    data.update(task_status="needs_review", issues=[{
        "issue_id": "missing-passport", "code": "missing_source", "severity": "error",
        "message": "No usable passport candidate.", "field_ids": ["passport"],
    }], review_requests=[{"field_id": "passport", "action": "request_documents", "message": "Supply passport."}])
    return data


def test_missing_requires_document_request_and_null_value():
    data = missing_result()
    assert parse(data).fields[1].suggested_value is None
    data["review_requests"][0]["action"] = "request_confirmation"
    with pytest.raises(ValidationError):
        parse(data)


def test_pending_calculation_keeps_inputs_and_no_final_value():
    data = read()
    data["fields"][-1].update(status="needs_calculation", suggested_value=None, issue_ids=["pending-calculation"])
    data.update(task_status="needs_review", issues=[{
        "issue_id": "pending-calculation", "code": "pending_calculation", "severity": "warning",
        "message": "Calculation output awaits confirmation.", "field_ids": ["days"],
    }], review_requests=[{"field_id": "days", "action": "calculate", "message": "Confirm calculation."}])
    result = parse(data)
    assert result.fields[-1].suggested_value is None
    assert len(result.fields[-1].derivation.input_fact_ids) == 2


def test_conditions_are_declarative_and_unknown_requires_review():
    data = read()
    data["form_schema"]["fields"][1]["required_when"] = {
        "field_id": "name", "value": {"kind": "text", "value": "Someone Else"},
    }
    with pytest.raises(ValidationError, match="false field condition"):
        parse(data)
    passport = data["fields"][1]
    passport.update(status="not_applicable", suggested_value=None, selected_candidate_id=None)
    assert parse(data).fields[1].status == "not_applicable"
    data["form_schema"]["fields"][0]["required_when"] = {
        "field_id": "passport", "value": {"kind": "text", "value": "P00001234"},
    }
    with pytest.raises(ValidationError, match="cyclic"):
        parse(data)


@pytest.mark.parametrize("relative_path", ["../outside.txt", "/root.txt", "C:/secret.txt", "C:secret.txt",
                                          "\\\\host\\share.txt", "documents/../secret.txt", "a//b.txt", "."])
def test_paths_cannot_escape_task(relative_path):
    data = read(filename="input.json")["documents"][0]
    data["relative_path"] = relative_path
    with pytest.raises(ValidationError):
        Document.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("locator", [
    {"kind": "page", "page": 0, "bbox": [0.0, 0.0, 1.0, 1.0]},
    {"kind": "page", "page": 1, "bbox": [0.0, 0.0, 1.1, 1.0]},
    {"kind": "page", "page": 1, "bbox": [0.5, 0.5, 0.1, 0.9]},
    {"kind": "page", "page": 1, "bbox": [0.0, 0.0, 1.0, 1.0], "source_rotation_degrees": 90},
])
def test_invalid_page_locations(locator):
    with pytest.raises(ValidationError):
        PageLocator.model_validate_json(json.dumps(locator))


@pytest.mark.parametrize("cell", ["A0", "a1", "XFE1", "A1048577", "B2:A1", "A1:B2:C3"])
def test_invalid_excel_addresses(cell):
    with pytest.raises(ValidationError):
        CellLocator(sheet="Form", cell_range=cell)


def test_typed_values_preserve_identifiers_and_reject_invalid_dates():
    assert parse(read()).facts[2].normalized_value.value == "P00001234"
    with pytest.raises(ValidationError):
        IntegerValue(value=True)
    with pytest.raises(ValidationError):
        DateValue.model_validate_json('{"kind":"date","value":"2026-02-30"}')


def test_gold_is_independent_of_prediction_ids():
    task = parse(read(filename="input.json"), TaskInput)
    gold = parse(read(filename="ground_truth.json"), GroundTruth)
    validate_ground_truth(task, gold)
    assert {f.gold_field_id for f in gold.expected_fields}.isdisjoint({f["field_id"] for f in read()["fields"]})
    verify_artifacts(task, EXAMPLES / "normal", truth=gold)  # No predicted result is needed.


@pytest.mark.parametrize("mutation", [
    lambda g: g["expected_fields"][0].update(expected_action="request_documents"),
    lambda g: g["expected_fields"][0].update(accepted_values=[None]),
    lambda g: g["expected_fields"][0]["accepted_values"][0].update(value="unsupported gold value"),
    lambda g: g["expected_fields"][0].update(evidence_alternatives=[]),
    lambda g: g["expected_fields"].pop(),
])
def test_invalid_ground_truth(mutation):
    gold = read(filename="ground_truth.json")
    mutation(gold)
    with pytest.raises(ValidationError):
        parse(gold, GroundTruth)


def test_file_hash_and_physical_evidence_are_checked(tmp_path):
    import shutil

    directory = tmp_path / "example"
    shutil.copytree(EXAMPLES / "normal", directory)
    task = parse(read(filename="input.json"), TaskInput)
    (directory / "documents" / "passport.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_artifacts(task, directory)
    result = parse(read())
    # Change the excerpt and all its matching evidence together: structural checks pass,
    # but checking the original file must still fail.
    result.parsed_documents[1].segments[0].text = "Invented header"
    with pytest.raises(ValueError, match="physical source"):
        verify_artifacts(result.task_input, EXAMPLES / "normal", result.parsed_documents)


def test_gold_quote_is_checked_against_file():
    task = parse(read(filename="input.json"), TaskInput)
    gold = parse(read(filename="ground_truth.json"), GroundTruth)
    gold.expected_fields[0].evidence_alternatives[0][0].quote = "FakeName"
    with pytest.raises(ValueError, match="gold quote"):
        verify_artifacts(task, EXAMPLES / "normal", truth=gold)


def test_exported_schemas_validate_examples_and_match_committed_schemas(tmp_path):
    export_schemas(tmp_path)
    for model, filename in [(TaskInput, "input.json"), (FillingResult, "result.json"), (GroundTruth, "ground_truth.json")]:
        schema_name = f"{model.__name__}.schema.json"
        schema = json.loads((tmp_path / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for name in ("normal", "conflict"):
            validator.validate(read(name, filename))
        assert schema == json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))


def test_failure_can_preserve_error_without_form_schema():
    data = read()
    data.update(form_schema=None, fields=[], candidates=[], issues=[], review_requests=[],
                task_status="failed", errors=[{"stage": "form_understanding", "code": "unreadable_form",
                                               "message": "Failed to understand target form."}])
    assert parse(data).task_status == "failed"
