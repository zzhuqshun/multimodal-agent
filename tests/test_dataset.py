import hashlib
import json
import shutil

import pytest

from smartfill.dataset import generate_dataset
from smartfill.dataset_audit import audit_dataset


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    directory = tmp_path_factory.mktemp("corpus") / "dev"
    summary = generate_dataset(directory)
    assert summary["artifact_audit"] == "passed"
    return directory


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh_record(root, task_id, filename):
    manifest = read(root / "manifest.json")
    record = next(r for r in manifest["tasks"] if r["task_id"] == task_id)
    record["files"][filename] = hashlib.sha256((root / record["task_path"] / filename).read_bytes()).hexdigest()
    write(root / "manifest.json", manifest)


def test_full_corpus_and_blank_template_audit(corpus):
    summary = audit_dataset(corpus)
    assert summary["tasks"] == 15
    assert summary["categories"] == {"normal": 6, "conflict": 5, "missing": 4}
    assert summary["fields"] == 175
    assert summary["human_reviewed_tasks"] == summary["embedded_model_predictions"] == 0
    assert "model_runs" not in summary
    assert "not inspected" in summary["audit_scope"]
    manifest = read(corpus / "manifest.json")
    for record in manifest["tasks"]:
        task = read(corpus / record["task_path"] / "input.json")
        assert all(d["relative_path"].startswith("documents/") for d in task["documents"])
        assert all("gold" not in d["relative_path"] and "annotations" not in d["relative_path"] for d in task["documents"])
        assert not (corpus / record["task_path"] / "result.json").exists()


@pytest.mark.parametrize("number,field,status,issue", [
    (7, "passport", "conflict", "source_conflict"),
    (8, "expiry", "conflict", "source_conflict"),
    (9, "visit1_start", "conflict", "source_conflict"),
    (10, "name", "conflict", "source_conflict"),
    (11, "return", "conflict", "visa_range_mismatch"),
    (11, "days", "review_required", "upstream_conflict"),
    (12, "visa_end", "missing", "missing_source"),
    (13, "address", "missing", "missing_source"),
    (14, "return", "missing", "missing_source"),
    (14, "days", "missing", "missing_calculation_input"),
    (15, "visit2_contact", "missing", "missing_source"),
])
def test_scenario_semantics(corpus, number, field, status, issue):
    truth = read(corpus / "tasks" / f"DEV-{number:03d}" / "ground_truth.json")
    fields = {f["gold_field_id"].removeprefix("gold-"): f for f in truth["expected_fields"]}
    item = fields[field]
    assert item["accepted_values"] == [None]
    assert item["expected_status"] == status
    assert item["expected_issue_codes"] == [issue]
    assert fields["departure"]["expected_status"] == "verified"
    if number in (9, 15):
        assert fields["visit2_host"]["expected_status"] == "verified"


def test_date_alias_and_distractor_scenarios(corpus):
    for number in (2, 4, 5, 6):
        truth = read(corpus / "tasks" / f"DEV-{number:03d}" / "ground_truth.json")
        assert all(f["expected_status"] == "verified" for f in truth["expected_fields"])
        if number == 4:
            name = next(f for f in truth["expected_fields"] if f["gold_field_id"] == "gold-name")
            assert len(name["expected_candidates"][-1]["evidence"]) == 3
        if number == 5:
            path = corpus / "tasks" / "DEV-005" / "documents" / "invitation-1.txt"
            assert "访问开始日" in path.read_text() and "签发日期" in path.read_text()


def test_fixed_seed_produces_identical_bytes(corpus, tmp_path):
    other = tmp_path / "same"
    generate_dataset(other)
    expected = {str(p.relative_to(corpus)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in corpus.rglob("*") if p.is_file()}
    actual = {str(p.relative_to(other)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in other.rglob("*") if p.is_file()}
    assert actual == expected


def test_existing_output_is_preserved(corpus):
    original = (corpus / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        generate_dataset(corpus)
    assert (corpus / "manifest.json").read_bytes() == original


@pytest.mark.parametrize("mutation,expected", [
    ("hash", "hash mismatch"),
    ("gold", "gold value differs"),
    ("location", "label outside"),
    ("extra", "unindexed"),
    ("path", "unsafe manifest"),
    ("symlink", "task directory escapes"),
    ("review", "incorrect split/review"),
    ("calculation", "calculation input differs"),
])
def test_auditor_rejects_corrupted_or_forged_corpus(corpus, tmp_path, mutation, expected):
    root = tmp_path / "tampered"
    shutil.copytree(corpus, root)
    task_dir = root / "tasks/DEV-001"
    if mutation == "hash":
        with (task_dir / "documents/passport.txt").open("a") as stream:
            stream.write("altered")
    elif mutation in ("gold", "location", "calculation"):
        truth = read(task_dir / "ground_truth.json")
        if mutation == "gold":
            field = truth["expected_fields"][0]
            field["accepted_values"][0]["value"] = "Unsupported Person"
            field["expected_candidates"][0]["value"]["value"] = "Unsupported Person"
        elif mutation == "calculation":
            from datetime import date, timedelta
            field = next(f for f in truth["expected_fields"] if f["gold_field_id"] == "gold-days")
            for source in field["expected_calculation"]["inputs"]:
                value = source["value"]["value"]
                source["value"]["value"] = (date.fromisoformat(value) + timedelta(days=1)).isoformat()
        else:
            truth["expected_form"]["fields"][0]["target_locator"]["bbox"] = [0.01, 0.01, 0.1, 0.05]
        write(task_dir / "ground_truth.json", truth)
        refresh_record(root, "DEV-001", "ground_truth.json")
    elif mutation == "extra":
        (task_dir / "documents/answer.txt").write_text("hidden answer")
        # Keep the extra file outside documents so the final physical-index guard is tested.
        (task_dir / "documents/answer.txt").rename(root / "extra-answer.txt")
    elif mutation == "symlink":
        escaped = tmp_path / "escaped-task"
        task_dir.rename(escaped)
        task_dir.symlink_to(escaped, target_is_directory=True)
    else:
        manifest = read(root / "manifest.json")
        if mutation == "path":
            manifest["templates"]["../escape.pdf"] = "0" * 64
        else:
            manifest["tasks"][0]["human_reviewed"] = True
        write(root / "manifest.json", manifest)
    with pytest.raises(ValueError, match=expected):
        audit_dataset(root)
