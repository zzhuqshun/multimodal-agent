import json
import shutil
from pathlib import Path

import pytest

from smartfill import model_baseline
from smartfill.baseline import extract_sources
from smartfill.dataset import generate_dataset
from smartfill.experiments import run_model_batch
from smartfill.model_api import ModelConfig

CONFIG = ModelConfig("http://127.0.0.1:1/v1", "fake-model", "", 1)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    path = tmp_path_factory.mktemp("model-baseline") / "dev"
    generate_dataset(path)
    return path


def fake_provider(config, route, payload):
    """A deterministic mock exercises wiring, not a claim about model accuracy."""
    assert route == "/chat/completions"
    visible = json.loads(payload["messages"][1]["content"])
    references = [{"document_id": d["document_id"],
                   "segments": [{"segment_id": sid, "text": text,
                                 "locator": {"kind": "text", "line_start": int(sid[5:]),
                                             "line_end": int(sid[5:])}} for sid, text in d["segments"]]}
                  for d in visible["materials"]]
    evidence, facts, _ = extract_sources(references)
    by_id = {e["evidence_id"]: e for e in evidence}
    rows = []
    for fact in facts:
        if fact["predicate"] not in visible["allowed_keys"]:
            continue
        source = by_id[fact["evidence_ids"][0]]
        rows.append([fact["predicate"], source["document_id"], source["segment_id"], fact["raw_value"]])
    extracted = {"sources": rows}
    if payload["messages"][0]["content"] == model_baseline.DOCUMENT_SYSTEM_PROMPT:
        used = {row[2] for row in rows}
        extracted["sources"] = [{"key": r[0], "segment_id": r[2], "quote": r[3]} for r in rows]
        extracted["ignored"] = [s["segment_id"] for s in references[0]["segments"]
                                if s["segment_id"] not in used]
    return {"model": config.model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(extracted)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


@pytest.mark.parametrize("number", [1, 4, 7, 11, 14])
def test_model_wiring_grounding_and_visible_inputs(corpus, tmp_path, monkeypatch, number):
    root = tmp_path / "task"
    shutil.copytree(corpus / "tasks" / f"DEV-{number:03d}", root)
    (root / "ground_truth.json").unlink()
    (root / "annotations.json").unlink()
    task_path = root / "input.json"
    task = json.loads(task_path.read_text())
    task["task_id"] = "renamed-task"
    mapping = {d["document_id"]: f"source-{i}" for i, d in enumerate(task["documents"])}
    task["target_document_id"] = mapping[task["target_document_id"]]
    for document in task["documents"]:
        document["document_id"] = mapping[document["document_id"]]
    task_path.write_text(json.dumps(task))
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path.name not in {"ground_truth.json", "annotations.json", "manifest.json"}
        return original(path, *args, **kwargs)

    def provider(config, route, payload):
        text = json.dumps(payload)
        assert "gold_field_id" not in text and "ground_truth" not in text and "expected_fields" not in text
        assert f"DEV-{number:03d}" not in text
        return fake_provider(config, route, payload)

    monkeypatch.setattr(Path, "open", guarded)
    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(root, CONFIG, trace, strategy="all")
    assert result.task_status != "failed"
    assert result.run_metadata.mode == "model_baseline"
    assert result.run_metadata.model_id == "fake-model"
    assert result.run_metadata.input_tokens == 100
    assert result.run_metadata.output_tokens == 50
    assert all(c.method == "llm" for c in result.candidates)
    assert all(e.origin == "vlm" for e in result.evidence)
    assert (trace / "request.json").exists() and (trace / "response.json").exists()
    with pytest.raises(ValueError, match="already exists"):
        model_baseline.fill_model_task(root, CONFIG, trace, strategy="all")


@pytest.mark.parametrize("mutation", ["quote", "segment", "key", "duplicate", "extra", "json", "truncated", "usage", "model"])
def test_untrusted_model_response_fails_closed(corpus, tmp_path, monkeypatch, mutation):
    def provider(config, route, payload):
        response = fake_provider(config, route, payload)
        choice = response["choices"][0]
        content = json.loads(choice["message"]["content"])
        row = content["sources"][0]
        if mutation == "quote":
            row[3] = "invented evidence"
        elif mutation == "segment":
            row[2] = "line-999"
        elif mutation == "key":
            row[0] = "unregistered-key"
        elif mutation == "duplicate":
            content["sources"].append(row.copy())
        elif mutation == "extra":
            content["answer"] = "should not pass"
        elif mutation == "truncated":
            choice["finish_reason"] = "length"
        elif mutation == "usage":
            response["usage"]["prompt_tokens"] = -1
        elif mutation == "model":
            response["model"] = "different-model"
        choice["message"]["content"] = "{" if mutation == "json" else json.dumps(content)
        return response

    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, trace, strategy="all")
    assert result.task_status == "failed"
    assert result.fields == [] and result.candidates == []
    assert result.errors[0].stage == "extraction"
    assert (trace / "response.json").exists() and (trace / "error.json").exists()


def test_transport_failure_preserves_request_without_fallback(corpus, tmp_path, monkeypatch):
    def provider(*args):
        raise ValueError("model service unreachable or timed out")
    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, trace, strategy="all")
    assert result.task_status == "failed" and not result.fields
    assert result.run_metadata.input_tokens is None
    assert (trace / "request.json").exists() and (trace / "error.json").exists()
    assert not (trace / "response.json").exists()


def test_missing_usage_stays_unknown(corpus, tmp_path, monkeypatch):
    def provider(*args):
        response = fake_provider(*args)
        response.pop("usage")
        return response
    monkeypatch.setattr(model_baseline, "request_json", provider)
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, tmp_path / "trace", strategy="all")
    assert result.task_status == "completed"
    assert result.run_metadata.input_tokens is None and result.run_metadata.output_tokens is None


def test_batch_predictions_and_raw_responses_precede_gold(corpus, tmp_path, monkeypatch):
    dataset = tmp_path / "dev"
    for number in (1, 14):
        shutil.copytree(corpus / "tasks" / f"DEV-{number:03d}", dataset / "tasks" / f"DEV-{number:03d}")
    output = tmp_path / "run"
    calls = []
    original_read = Path.read_bytes

    def provider(*args):
        calls.append(1)
        return fake_provider(*args)

    def guarded_read(path):
        if path.name == "ground_truth.json":
            assert len(calls) == 2
            assert len(list(output.glob("tasks/*/result.json"))) == 2
            assert len(list(output.glob("tasks/*/model/response.json"))) == 2
        return original_read(path)

    monkeypatch.setattr(model_baseline, "request_json", provider)
    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    summary = run_model_batch(dataset, CONFIG, output, strategy="all")
    assert summary["model_calls"] == 2 and summary["model_id"] == CONFIG.model
    assert summary["metrics"]["task_pass_rate"]["value"] == 1
    assert summary["token_usage"]["input_tokens"] == {"sum_reported": 200, "reported_tasks": 2, "tasks": 2}


@pytest.mark.parametrize("number", [1, 4, 7, 9, 11, 14])
def test_document_strategy_processes_every_document(corpus, tmp_path, monkeypatch, number):
    root = tmp_path / "task"
    shutil.copytree(corpus / "tasks" / f"DEV-{number:03d}", root)
    (root / "ground_truth.json").unlink()
    (root / "annotations.json").unlink()
    original = Path.open
    calls = []

    def guarded(path, *args, **kwargs):
        assert path.name not in {"ground_truth.json", "annotations.json", "manifest.json"}
        return original(path, *args, **kwargs)

    def provider(config, route, payload):
        visible = json.loads(payload["messages"][1]["content"])
        assert len(visible["materials"]) == 1
        calls.append(visible["materials"][0]["document_id"])
        return fake_provider(config, route, payload)

    monkeypatch.setattr(Path, "open", guarded)
    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(root, CONFIG, trace, repair_attempts=0)
    expected = [d.document_id for d in result.task_input.documents if d.role == "reference"]
    assert calls == expected
    assert result.task_status != "failed"
    assert result.run_metadata.prompt_version == model_baseline.DOCUMENT_PROMPT_VERSION
    assert result.run_metadata.input_tokens == len(calls) * 100
    assert result.run_metadata.output_tokens == len(calls) * 50
    assert len(list(trace.glob("document-*/coverage.json"))) == len(calls)
    assert len(list(trace.glob("document-*/response.json"))) == len(calls)


@pytest.mark.parametrize("mutation", ["unaccounted", "relevant_ignored", "overlap", "duplicate_ignored", "foreign", "wrong_key", "quote"])
def test_document_coverage_rejects_omissions_and_bad_grounding(corpus, tmp_path, monkeypatch, mutation):
    def provider(*args):
        response = fake_provider(*args)
        content = json.loads(response["choices"][0]["message"]["content"])
        row = content["sources"][0]
        if mutation == "unaccounted":
            content["ignored"].pop()
        elif mutation == "relevant_ignored":
            content["sources"].pop(0)
            content["ignored"].append(row["segment_id"])
        elif mutation == "overlap":
            content["ignored"].append(row["segment_id"])
        elif mutation == "duplicate_ignored":
            content["ignored"].append(content["ignored"][0])
        elif mutation == "foreign":
            row["segment_id"] = "line-999"
        elif mutation == "wrong_key":
            row["key"] = "name"
        elif mutation == "quote":
            row["quote"] = "hallucinated quote"
        response["choices"][0]["message"]["content"] = json.dumps(content)
        return response

    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-007", CONFIG, trace, repair_attempts=0)
    assert result.task_status == "failed" and not result.fields
    assert len(list(trace.glob("document-*/request.json"))) == 1
    error = json.loads((trace / "document-0001/error.json").read_text())
    assert error["step"] == ("grounding" if mutation == "quote" else "coverage")


def test_document_transport_failure_preserves_completed_calls(corpus, tmp_path, monkeypatch):
    calls = []

    def provider(*args):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("model service unreachable or timed out")
        return fake_provider(*args)

    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, trace, repair_attempts=0)
    assert result.task_status == "failed" and len(calls) == 2
    assert result.run_metadata.input_tokens is None and result.run_metadata.output_tokens is None
    assert (trace / "document-0001/coverage.json").exists()
    assert (trace / "document-0002/request.json").exists()
    assert not (trace / "document-0002/response.json").exists()
    assert (trace / "document-0002/error.json").exists()


def test_document_batch_saves_all_predictions_before_gold(corpus, tmp_path, monkeypatch):
    dataset = tmp_path / "dev"
    expected_calls = 0
    for number in (4, 7):
        source = corpus / "tasks" / f"DEV-{number:03d}"
        shutil.copytree(source, dataset / "tasks" / source.name)
        expected_calls += len(json.loads((source / "input.json").read_bytes())["documents"]) - 1
    output = tmp_path / "run"
    calls = []
    original_read = Path.read_bytes

    def provider(*args):
        calls.append(1)
        return fake_provider(*args)

    def guarded(path):
        if path.name == "ground_truth.json":
            assert len(calls) == expected_calls
            assert len(list(output.glob("tasks/*/result.json"))) == 2
            assert len(list(output.glob("tasks/*/model/**/response.json"))) == expected_calls
        return original_read(path)

    monkeypatch.setattr(model_baseline, "request_json", provider)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    summary = run_model_batch(dataset, CONFIG, output, repair_attempts=0)
    assert summary["model_calls"] == expected_calls
    assert summary["metrics"]["task_pass_rate"]["value"] == 1
    assert summary["baseline"] == model_baseline.DOCUMENT_VERSION
    assert summary["token_usage"]["input_tokens"]["sum_reported"] == 100 * expected_calls
    assert summary["request_token_usage"]["prompt_tokens"]["sum_reported"] == 100 * expected_calls


def test_document_missing_counter_does_not_claim_complete_usage(corpus, tmp_path, monkeypatch):
    calls = []

    def provider(*args):
        calls.append(1)
        response = fake_provider(*args)
        if len(calls) == 2:
            response["usage"].pop("prompt_tokens")
        return response

    monkeypatch.setattr(model_baseline, "request_json", provider)
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, tmp_path / "trace", repair_attempts=0)
    assert result.task_status == "completed"
    assert result.run_metadata.input_tokens is None
    assert result.run_metadata.output_tokens == 50 * len(calls)


def test_document_batch_counts_usage_before_later_transport_failure(corpus, tmp_path, monkeypatch):
    dataset = tmp_path / "dev"
    shutil.copytree(corpus / "tasks" / "DEV-001", dataset / "tasks" / "DEV-001")
    calls = []

    def provider(*args):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("model service unreachable or timed out")
        return fake_provider(*args)

    monkeypatch.setattr(model_baseline, "request_json", provider)
    summary = run_model_batch(dataset, CONFIG, tmp_path / "run", repair_attempts=0)
    assert summary["task_statuses"] == {"failed": 1}
    assert summary["model_calls"] == 2
    assert summary["token_usage"]["input_tokens"]["reported_tasks"] == 0
    assert summary["request_token_usage"]["prompt_tokens"] == {
        "sum_reported": 100, "reported_responses": 1, "saved_responses": 1, "request_attempts": 2}


def test_one_validation_repair_preserves_both_attempts_and_usage(corpus, tmp_path, monkeypatch):
    dataset = tmp_path / "dev"
    shutil.copytree(corpus / "tasks" / "DEV-001", dataset / "tasks" / "DEV-001")
    calls = []

    def provider(config, route, payload):
        calls.append(payload)
        response = fake_provider(config, route, payload)
        if len(calls) == 1:
            content = json.loads(response["choices"][0]["message"]["content"])
            row = content["sources"].pop(0)
            content["ignored"].append(row["segment_id"])
            response["choices"][0]["message"]["content"] = json.dumps(content)
        elif len(calls) == 2:
            feedback = json.loads(payload["messages"][-1]["content"])
            assert feedback["required_visible_segments"]
            assert "TEST-" not in json.dumps(feedback)
            assert "expected_fields" not in json.dumps(feedback)
        return response

    monkeypatch.setattr(model_baseline, "request_json", provider)
    output = tmp_path / "run"
    summary = run_model_batch(dataset, CONFIG, output)
    assert summary["metrics"]["task_pass_rate"]["value"] == 1
    assert summary["validation_repairs"] == 1
    assert summary["model_calls"] == len(calls)
    assert summary["baseline"] == model_baseline.REPAIR_VERSION
    assert summary["token_usage"]["input_tokens"]["sum_reported"] == len(calls) * 100
    assert summary["request_token_usage"]["prompt_tokens"]["sum_reported"] == len(calls) * 100
    trace = output / "tasks/task-0001/model/document-0001"
    assert (trace / "attempt-0001/error.json").exists()
    assert (trace / "attempt-0001/feedback.json").exists()
    assert (trace / "attempt-0002/coverage.json").exists()
    assert len(list(trace.glob("attempt-*/response.json"))) == 2


def test_validation_repair_stops_after_second_rejection(corpus, tmp_path, monkeypatch):
    calls = []

    def provider(*args):
        calls.append(1)
        response = fake_provider(*args)
        content = json.loads(response["choices"][0]["message"]["content"])
        content["ignored"].pop()
        response["choices"][0]["message"]["content"] = json.dumps(content)
        return response

    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, trace)
    assert result.task_status == "failed" and not result.fields
    assert len(calls) == 2
    assert len(list(trace.glob("**/error.json"))) == 2
    assert len(list(trace.glob("**/feedback.json"))) == 1


def test_validation_repair_does_not_retry_transport_error(corpus, tmp_path, monkeypatch):
    calls = []

    def provider(*args):
        calls.append(1)
        raise ValueError("model service unreachable or timed out")

    monkeypatch.setattr(model_baseline, "request_json", provider)
    trace = tmp_path / "trace"
    result = model_baseline.fill_model_task(corpus / "tasks" / "DEV-001", CONFIG, trace)
    assert result.task_status == "failed" and len(calls) == 1
    assert not list(trace.glob("**/feedback.json"))


def test_batch_preserves_report_for_malformed_response_usage(corpus, tmp_path, monkeypatch):
    dataset = tmp_path / "dev"
    shutil.copytree(corpus / "tasks" / "DEV-001", dataset / "tasks" / "DEV-001")

    def provider(*args):
        response = fake_provider(*args)
        response["usage"] = ["not-a-token-counter"]
        return response

    monkeypatch.setattr(model_baseline, "request_json", provider)
    summary = run_model_batch(dataset, CONFIG, tmp_path / "run")
    assert summary["task_statuses"] == {"failed": 1}
    assert summary["model_calls"] == 1
    assert summary["request_token_usage"]["prompt_tokens"]["reported_responses"] == 0
    assert summary["request_token_usage"]["prompt_tokens"]["saved_responses"] == 1
