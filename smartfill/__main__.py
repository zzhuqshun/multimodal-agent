"""CLI for contracts, physical-file rule filling and independent development evaluation."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .contracts import FillingResult, GroundTruth, TaskInput
from .integrity import require, verify_artifacts


def validate_example(directory: Path) -> dict:
    task = TaskInput.model_validate_json((directory / "input.json").read_bytes())
    result = FillingResult.model_validate_json((directory / "result.json").read_bytes())
    require(task == result.task_input, "result task_input differs from input.json")
    # Ground truth is loaded separately, and is never provided to the result constructor.
    truth = GroundTruth.model_validate_json((directory / "ground_truth.json").read_bytes())
    verify_artifacts(task, directory, result.parsed_documents, truth)
    return {
        "task_id": task.task_id,
        "task_status": result.task_status,
        "fields": {field.field_id: field.status for field in result.fields},
        "pending_requests": len(result.review_requests),
        "artifact_integrity": "passed",
        "ground_truth_integrity": "passed",
    }


def export_schemas(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for model in (TaskInput, FillingResult, GroundTruth):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:smartfill:0.1.0:{model.__name__}"
        (directory / f"{model.__name__}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="validate a handcrafted example directory")
    validate.add_argument("directory", type=Path)
    export = subcommands.add_parser("export-schemas", help="export Draft 2020-12 schemas")
    export.add_argument("directory", type=Path)
    generate = subcommands.add_parser("generate-dev", help="generate 15 fictional PDF/Excel development tasks")
    generate.add_argument("--output", type=Path, default=Path("data/dev/v0.1.0"))
    generate.add_argument("--seed", type=int, default=20261012)
    generate.add_argument("--font", type=Path, default=Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"))
    audit = subcommands.add_parser("audit-dataset", help="read back and audit physical files and independent gold")
    audit.add_argument("directory", type=Path)
    fill = subcommands.add_parser("fill-rule", help="fill one task using only declared physical materials")
    fill.add_argument("directory", type=Path)
    fill.add_argument("--output", required=True, type=Path)
    run = subcommands.add_parser("run-rule-baseline", help="save all predictions, then independently evaluate")
    run.add_argument("directory", type=Path)
    run.add_argument("--output", type=Path)
    evaluate = subcommands.add_parser("evaluate", help="evaluate a saved prediction against independent gold")
    evaluate.add_argument("directory", type=Path)
    evaluate.add_argument("result", type=Path)
    subcommands.add_parser("check-model", help="check configured server model and one fixed text prompt")
    args = parser.parse_args()
    try:
        if args.command == "check-model":
            from .model_api import ModelConfig, check_model
            print(json.dumps(check_model(ModelConfig.from_env()), ensure_ascii=False, indent=2))
        elif args.command == "validate":
            print(json.dumps(validate_example(args.directory), ensure_ascii=True, indent=2))
        elif args.command == "generate-dev":
            from .dataset import generate_dataset
            print(json.dumps(generate_dataset(args.output, args.seed, args.font), ensure_ascii=False, indent=2))
        elif args.command == "audit-dataset":
            from .dataset_audit import audit_dataset
            print(json.dumps(audit_dataset(args.directory), ensure_ascii=False, indent=2))
        elif args.command == "fill-rule":
            from .baseline import fill_task
            from .experiments import write_new
            require(not args.output.exists(), "output already exists")
            require(not args.output.resolve().is_relative_to(args.directory.resolve()),
                    "prediction output must be outside the task directory")
            result = fill_task(args.directory)
            write_new(args.output, result.model_dump(mode="json"))
            print(json.dumps({"task_id": result.task_id, "task_status": result.task_status,
                              "output": str(args.output.absolute())}, ensure_ascii=False, indent=2))
            return 1 if result.task_status == "failed" else 0
        elif args.command == "run-rule-baseline":
            from .experiments import run_rule_batch
            print(json.dumps(run_rule_batch(args.directory, args.output), ensure_ascii=False, indent=2))
        elif args.command == "evaluate":
            from .experiments import evaluate_saved
            print(json.dumps(evaluate_saved(args.directory, args.result), ensure_ascii=False, indent=2))
        else:
            export_schemas(args.directory)
            print("Exported TaskInput, FillingResult and GroundTruth schemas.")
    except (OSError, ValueError, ValidationError) as error:
        # Avoid dumping Pydantic's input payload, which may contain source material.
        message = "contract validation failed" if isinstance(error, ValidationError) else str(error)
        parser.exit(1, f"Error: {message}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
