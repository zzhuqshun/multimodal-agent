import hashlib
import json
import shutil
from pathlib import Path

import pytest

from smartfill.baseline import fill_task
from smartfill.contracts import FillingResult, GroundTruth
from smartfill.dataset import generate_dataset
from smartfill.evaluate import aggregate, evaluate_task
from smartfill.experiments import run_rule_batch
from smartfill.integrity import verify_artifacts


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("baseline") / "dev"
    generate_dataset(root)
    return root


@pytest.fixture(scope="module")
def predictions(corpus):
    return [fill_task(corpus / "tasks" / f"DEV-{i:03d}") for i in range(1, 16)]


def gold(corpus, number):
    return GroundTruth.model_validate_json(
        (corpus / "tasks" / f"DEV-{number:03d}" / "ground_truth.json").read_bytes())


def validated(payload):
    return FillingResult.model_validate_json(json.dumps(payload))


def test_all_physical_tasks_match_independent_answers(corpus, predictions):
    reports = [evaluate_task(r, gold(corpus, i)) for i, r in enumerate(predictions, 1)]
    summary = aggregate(reports)
    assert summary["tasks"] == 15
    assert summary["counts"]["fully_correct_fields"] == 175
    assert summary["counts"]["matched_candidates"] == 190
    assert summary["counts"]["correct_calculations"] == 13
    assert summary["metrics"]["task_pass_rate"]["value"] == 1
    assert summary["task_statuses"] == {"completed": 6, "needs_review": 9}
    assert summary["pending_requests"] == 12
    for number, result in enumerate(predictions, 1):
        assert result.run_metadata.mode == "rule_baseline"
        assert result.run_metadata.model_id is None
        assert result.timing.total_ms > 0
        verify_artifacts(result.task_input, corpus / "tasks" / f"DEV-{number:03d}", result.parsed_documents)
        assert not {f.field_id for f in result.fields} & {f.gold_field_id for f in gold(corpus, number).expected_fields}


def test_filling_has_no_answer_files_or_task_id_dependency(corpus, tmp_path, monkeypatch):
    root = tmp_path / "renamed"
    shutil.copytree(corpus / "tasks" / "DEV-004", root)
    (root / "ground_truth.json").unlink()
    (root / "annotations.json").unlink()
    path = root / "input.json"
    payload = json.loads(path.read_bytes())
    payload["task_id"] = "unseen-task"
    mapping = {d["document_id"]: f"source-{i}" for i, d in enumerate(payload["documents"])}
    payload["target_document_id"] = mapping[payload["target_document_id"]]
    for document in payload["documents"]:
        document["document_id"] = mapping[document["document_id"]]
    path.write_text(json.dumps(payload))
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path.name not in {"ground_truth.json", "annotations.json", "manifest.json"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    result = fill_task(root)
    assert result.task_id == "unseen-task"
    assert result.task_status == "completed"
    assert all(f.status == "verified" for f in result.fields)


@pytest.mark.parametrize("problem,stage", [("hash", "input"), ("profile", "validation")])
def test_failures_are_structured(corpus, tmp_path, problem, stage):
    root = tmp_path / problem
    shutil.copytree(corpus / "tasks" / "DEV-001", root)
    if problem == "hash":
        (root / "documents" / "passport.txt").write_text("changed")
    else:
        path = root / "input.json"
        payload = json.loads(path.read_bytes())
        payload["ruleset_version"] = "unsupported"
        path.write_text(json.dumps(payload))
    result = fill_task(root)
    assert result.task_status == "failed"
    assert result.errors[0].stage == stage
    assert result.form_schema is None and not result.fields


def test_malformed_date_requires_review_not_invented_missing(corpus, tmp_path):
    root = tmp_path / "invalid-date"
    shutil.copytree(corpus / "tasks" / "DEV-001", root)
    path = root / "documents" / "itinerary.txt"
    lines = path.read_text().splitlines()
    lines[2] = lines[2].split(":")[0] + ": 2026-99-99"
    path.write_text("\n".join(lines) + "\n")
    input_path = root / "input.json"
    task = json.loads(input_path.read_bytes())
    for d in task["documents"]:
        if d["relative_path"] == "documents/itinerary.txt":
            d["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    input_path.write_text(json.dumps(task))
    result = fill_task(root)
    forms = {f.field_id: f.semantic_key for f in result.form_schema.fields}
    fields = {forms[f.field_id]: f for f in result.fields}
    assert fields["return"].status == fields["days"].status == "review_required"
    assert fields["return"].suggested_value is None
    assert fields["days"].derivation is None
    assert {i.code for i in result.issues} == {"invalid_source_format", "upstream_conflict"}


def test_unknown_label_is_not_guessed(corpus, monkeypatch):
    from smartfill import parsing
    monkeypatch.delitem(parsing.LABELS, "姓名")
    result = fill_task(corpus / "tasks" / "DEV-001")
    assert result.task_status == "needs_review"
    unknown = next(f for f in result.form_schema.fields if f.label == "姓名")
    state = next(f for f in result.fields if f.field_id == unknown.field_id)
    assert state.status == "review_required" and state.suggested_value is None
    assert any(i.code == "unmapped_field" for i in result.issues)


def test_physical_form_text_forgery_is_rejected(corpus, predictions):
    payload = predictions[0].model_dump(mode="json")
    payload["parsed_documents"][0]["segments"][0]["text"] = "伪造字段"
    result = validated(payload)
    with pytest.raises(ValueError):
        verify_artifacts(result.task_input, corpus / "tasks" / "DEV-001", result.parsed_documents)


def test_evaluator_penalizes_missing_field(corpus, predictions):
    payload = predictions[0].model_dump(mode="json")
    field = payload["fields"][0]["field_id"]
    payload["fields"] = [f for f in payload["fields"] if f["field_id"] != field]
    payload["form_schema"]["fields"] = [f for f in payload["form_schema"]["fields"] if f["field_id"] != field]
    payload["candidates"] = [c for c in payload["candidates"] if c["field_id"] != field]
    summary = aggregate([evaluate_task(validated(payload), gold(corpus, 1))])
    assert summary["metrics"]["field_recall"]["value"] == 8 / 9
    assert summary["metrics"]["end_to_end_value_recall"]["value"] == 8 / 9
    assert summary["metrics"]["task_pass_rate"]["value"] == 0


def test_evaluator_rejects_duplicate_region_credit(corpus, predictions):
    payload = predictions[0].model_dump(mode="json")
    form = dict(payload["form_schema"]["fields"][0], field_id="duplicate")
    state = dict(payload["fields"][0], field_id="duplicate")
    old_ids = state["candidate_ids"]
    state["candidate_ids"] = []
    for candidate in list(payload["candidates"]):
        if candidate["candidate_id"] in old_ids:
            new = dict(candidate, candidate_id="copy-" + candidate["candidate_id"], field_id="duplicate")
            payload["candidates"].append(new)
            state["candidate_ids"].append(new["candidate_id"])
    state["selected_candidate_id"] = "copy-" + state["selected_candidate_id"]
    payload["form_schema"]["fields"].append(form)
    payload["fields"].append(state)
    summary = aggregate([evaluate_task(validated(payload), gold(corpus, 1))])
    assert summary["metrics"]["field_precision"]["value"] == 8 / 10
    assert summary["metrics"]["field_recall"]["value"] == 8 / 9
    assert summary["counts"]["wrong_fills"] == 2


def test_evaluator_detects_semantically_wrong_normalization(corpus, predictions):
    payload = predictions[0].model_dump(mode="json")
    fid = next(f["field_id"] for f in payload["form_schema"]["fields"] if f["semantic_key"] == "name")
    wrong = {"kind": "text", "value": "WRONG PERSON"}
    for fact in payload["facts"]:
        if fact["predicate"] == "name":
            fact["normalized_value"] = wrong
    for candidate in payload["candidates"]:
        if candidate["field_id"] == fid:
            candidate["value"] = wrong
    next(f for f in payload["fields"] if f["field_id"] == fid)["suggested_value"] = wrong
    result = validated(payload)  # Referential integrity alone cannot prove normalization.
    summary = aggregate([evaluate_task(result, gold(corpus, 1))])
    assert summary["counts"]["wrong_fills"] == 1
    assert summary["metrics"]["aligned_value_accuracy"]["value"] == 8 / 9
    assert summary["metrics"]["task_pass_rate"]["value"] == 0


def test_all_refusal_cannot_earn_value_credit(corpus, predictions):
    payload = predictions[0].model_dump(mode="json")
    payload["candidates"] = []
    payload["issues"], payload["review_requests"] = [], []
    payload["task_status"] = "needs_review"
    for field in payload["fields"]:
        fid, iid = field["field_id"], "missing-" + field["field_id"]
        field.update(status="missing", suggested_value=None, selected_candidate_id=None,
                     derivation=None, candidate_ids=[], evidence_ids=[], issue_ids=[iid])
        payload["issues"].append({"issue_id": iid, "code": "missing_source", "severity": "error",
                                  "message": "missing", "field_ids": [fid]})
        payload["review_requests"].append({"field_id": fid, "action": "request_documents", "message": "missing"})
    summary = aggregate([evaluate_task(validated(payload), gold(corpus, 1))])
    assert summary["metrics"]["end_to_end_value_recall"]["value"] == 0
    assert summary["metrics"]["task_pass_rate"]["value"] == 0
    assert summary["metrics"]["wrong_fill_rate"]["value"] is None


def test_evaluator_detects_dropped_same_value_candidate(corpus, predictions):
    payload = predictions[6].model_dump(mode="json")
    fid = next(f["field_id"] for f in payload["form_schema"]["fields"] if f["semantic_key"] == "passport")
    sources = [c for c in payload["candidates"] if c["field_id"] == fid]
    duplicate = next(c for c in sources if sum(c["value"] == other["value"] for other in sources) > 1)
    payload["candidates"] = [c for c in payload["candidates"] if c["candidate_id"] != duplicate["candidate_id"]]
    state = next(f for f in payload["fields"] if f["field_id"] == fid)
    state["candidate_ids"].remove(duplicate["candidate_id"])
    state["evidence_ids"] = list({e for c in payload["candidates"] if c["field_id"] == fid for e in c["evidence_ids"]})
    summary = aggregate([evaluate_task(validated(payload), gold(corpus, 7))])
    assert summary["metrics"]["source_candidate_recall"]["value"] < 1
    assert summary["metrics"]["task_pass_rate"]["value"] == 0


def test_batch_persists_all_predictions_before_any_gold(corpus, tmp_path, monkeypatch):
    from smartfill import experiments
    original_fill, original_read = experiments.fill_task, Path.read_bytes
    completed = []

    def fill(*args):
        result = original_fill(*args)
        completed.append(result.task_id)
        return result

    def read(path):
        if path.name == "ground_truth.json":
            assert len(completed) == 15
            assert len(list(output.glob("tasks/*/result.json"))) == 15
        return original_read(path)

    output = tmp_path / "run"
    monkeypatch.setattr(experiments, "fill_task", fill)
    monkeypatch.setattr(Path, "read_bytes", read)
    summary = run_rule_batch(corpus, output)
    assert summary["model_calls"] == 0
    assert summary["metrics"]["task_pass_rate"]["value"] == 1
    assert (output / "summary.json").exists()
    with pytest.raises(ValueError, match="already exists"):
        run_rule_batch(corpus, output)
    with pytest.raises(ValueError, match="outside"):
        run_rule_batch(corpus, corpus / "new-output")


def test_bad_gold_preserves_saved_predictions(corpus, tmp_path):
    root = tmp_path / "dev"
    shutil.copytree(corpus, root)
    (root / "tasks" / "DEV-001" / "ground_truth.json").write_text("{}")
    output = tmp_path / "failed-evaluation"
    with pytest.raises(ValueError):
        run_rule_batch(root, output)
    assert len(list(output.glob("tasks/*/result.json"))) == 15
    assert (output / "evaluation_error.json").exists()
    assert not (output / "summary.json").exists()
