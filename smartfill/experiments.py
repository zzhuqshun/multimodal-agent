"""Keep prediction generation before and separate from ground-truth evaluation."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from .baseline import fill_task
from .contracts import FillingResult, GroundTruth, TaskInput
from .evaluate import aggregate, evaluate_task
from .integrity import require, verify_artifacts


def write_new(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def evaluate_saved(task_directory: Path, result_path: Path) -> dict:
    """A standalone evaluator; the filling function never receives these annotations."""
    root = task_directory.resolve(strict=True)
    task = TaskInput.model_validate_json((root / "input.json").read_bytes())
    result = FillingResult.model_validate_json(result_path.read_bytes())
    require(result.task_input == task, "prediction used a different task input")
    truth = GroundTruth.model_validate_json((root / "ground_truth.json").read_bytes())
    verify_artifacts(task, root, result.parsed_documents, truth)
    return evaluate_task(result, truth)


def run_rule_batch(dataset: Path, output: Path | None = None) -> dict:
    return _run_batch(dataset, output)


def run_model_batch(dataset: Path, config, output: Path | None = None, strategy: str = "document", repair_attempts: int = 1) -> dict:
    require(strategy in ("all", "document"), "unsupported model extraction strategy")
    require(type(repair_attempts) is int and repair_attempts in (0, 1), "repair attempts must be zero or one")
    return _run_batch(dataset, output, config, strategy, repair_attempts)


def _run_batch(dataset: Path, output: Path | None, config=None, strategy="document", repair_attempts=0) -> dict:
    dataset = dataset.resolve(strict=True)
    # Discover task input paths without loading manifest, classes, anomaly tags or annotations.
    inputs = sorted((dataset / "tasks").glob("*/input.json"))
    require(bool(inputs), "no task inputs found")
    run_id = ("model-" if config else "rule-") + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    output = (output or Path("runs") / run_id).absolute()
    require(not output.exists(), "run directory already exists; choose a new output directory")
    require(not output.resolve().is_relative_to(dataset), "run outputs must be outside the dataset")
    output.mkdir(parents=True)
    jobs = []
    # Finish and persist every prediction before opening any gold file.
    for number, input_file in enumerate(inputs, 1):
        root = input_file.parent.resolve(strict=True)
        require(root.is_relative_to(dataset), "task directory escapes dataset")
        if config:
            from .model_baseline import fill_model_task
            result = fill_model_task(root, config, output / f"tasks/task-{number:04d}/model", run_id, strategy, repair_attempts)
        else:
            result = fill_task(root, run_id)
        relative = f"tasks/task-{number:04d}/result.json"
        write_new(output / relative, result.model_dump(mode="json"))
        jobs.append((root, output / relative))
    reports = []
    try:
        for number, (root, result_path) in enumerate(jobs, 1):
            report = evaluate_saved(root, result_path)
            write_new(output / f"tasks/task-{number:04d}/evaluation.json", report)
            reports.append(report)
    except (OSError, ValueError):
        write_new(output / "evaluation_error.json",
                  {"error": "evaluation could not complete; saved predictions were preserved"})
        raise
    first_metadata = FillingResult.model_validate_json(jobs[0][1].read_bytes()).run_metadata
    summary = aggregate(reports)
    summary.update({"run_id": run_id, "dataset": str(dataset), "directory": str(output),
                    "baseline": first_metadata.implementation_version,
                    "model_calls": len(list(output.glob("tasks/*/model/**/request.json"))),
                    "task_results": [{"task_id": r["task_id"], "task_pass": r["task_pass"],
                                      "task_status": r["task_status"],
                                      "result_path": f"tasks/task-{i:04d}/result.json"}
                                     for i, r in enumerate(reports, 1)]})
    if config:
        summary.update(model_id=config.model, strategy=strategy,
                       prompt_version=first_metadata.prompt_version,
                       validation_repairs=len(list(output.glob("tasks/*/model/**/feedback.json"))))
        usage = [FillingResult.model_validate_json(path.read_bytes()).run_metadata for _, path in jobs]
        summary["token_usage"] = {
            key: {"sum_reported": sum(getattr(m, key) or 0 for m in usage),
                  "reported_tasks": sum(getattr(m, key) is not None for m in usage),
                  "tasks": len(usage)} for key in ("input_tokens", "output_tokens")}
        response_paths = list(output.glob("tasks/*/model/**/response.json"))
        responses = [json.loads(path.read_bytes()) for path in response_paths]
        response_usage = [r["usage"] if isinstance(r.get("usage"), dict) else {} for r in responses]
        summary["request_token_usage"] = {
            key: {"sum_reported": sum(u[key] for u in response_usage if type(u.get(key)) is int and u[key] >= 0),
                  "reported_responses": sum(type(u.get(key)) is int and u[key] >= 0 for u in response_usage),
                  "saved_responses": len(response_paths), "request_attempts": summary["model_calls"]}
            for key in ("prompt_tokens", "completion_tokens")}
    write_new(output / "summary.json", summary)
    return summary
